"""One-to-one dispatch: maximize served requests, then minimize pickup seconds.

This produces an advisory plan, never an assignment mutation or route approval.
"""
from decimal import Decimal, ROUND_CEILING

from .calculations import check_energy, energy_values
from .models import DispatchInput, EnergyInput


def optimize_dispatch(value: DispatchInput | dict) -> dict:
    item = DispatchInput.model_validate(value)
    from ortools.graph.python import min_cost_flow
    nv, nr = len(item.vehicles), len(item.requests)
    common = {'solver': 'ortools-min-cost-flow', 'objective': 'max_served_then_min_pickup_seconds',
              'routing_verified': item.routing_verified, 'advisory_only': True,
              'cost_rounding': 'ceil_seconds_per_pickup_edge',
              'assumptions': ['Mỗi xe nhận tối đa một yêu cầu, không ghép nhiều khách hoặc tối ưu cả ca làm việc.',
                              'Kiểm tra pin gồm đoạn tới điểm đón và hành trình; chưa đặt chỗ trạm sạc hoặc điều xe thật.',
                              'Chi phí tối ưu dùng giây đón làm tròn lên; kiểm tra pin/thời gian chờ dùng số đo chưa làm tròn.']}
    if not nr:
        return {**common, 'status': 'OPTIMAL', 'assignments': [], 'unserved': [], 'served_count': 0,
                'total_pickup_seconds': 0, 'constraints_checked': True}

    eligible = {}
    failures = {j: set() for j in range(nr)}
    for i, vehicle in enumerate(item.vehicles):
        for j, request in enumerate(item.requests):
            reasons = failures[j]
            d, t = item.distance_matrix_m[i][j], item.duration_matrix_s[i][j]
            if not vehicle.available:
                reasons.add('vehicle_unavailable')
                continue
            if d is None or t is None:
                reasons.add('unreachable')
                continue
            if vehicle.seats < request.passengers:
                reasons.add('insufficient_seats')
                continue
            if Decimal(str(t)) > request.max_wait_s:
                reasons.add('pickup_wait_exceeded')
                continue
            energy = EnergyInput(profile=vehicle.profile, distance_m=Decimal(str(d))+request.distance_m,
                                 duration_s=Decimal(str(t))+request.duration_s)
            _, current, reserve, required = energy_values(energy)
            if current-required-reserve < 0:
                reasons.add('insufficient_energy_reserve')
                continue
            cost = int(Decimal(str(t)).to_integral_value(rounding=ROUND_CEILING))
            eligible[i, j] = (cost, energy)

    # One unserved request must cost more than ALL pickup costs combined, so
    # minimizing cannot sacrifice coverage to get a shorter pickup time.
    max_cost = max((entry[0] for entry in eligible.values()), default=0)
    unserved_penalty = nr*max_cost+1
    source, request_start, vehicle_start, sink = 0, 1, 1+nr, 1+nr+nv
    solver = min_cost_flow.SimpleMinCostFlow()
    for j in range(nr):
        solver.add_arc_with_capacity_and_unit_cost(source, request_start+j, 1, 0)
        solver.add_arc_with_capacity_and_unit_cost(request_start+j, sink, 1, unserved_penalty)
    for i in range(nv):
        solver.add_arc_with_capacity_and_unit_cost(vehicle_start+i, sink, 1, 0)
    edge_arcs = {}
    for (i, j), (cost, _) in eligible.items():
        edge_arcs[solver.add_arc_with_capacity_and_unit_cost(request_start+j, vehicle_start+i, 1, cost)] = (i, j)
    solver.set_node_supply(source, nr)
    solver.set_node_supply(sink, -nr)
    status = solver.solve()
    if status != solver.OPTIMAL:
        return {**common, 'status': 'SOLVER_FAILED', 'assignments': [],
                'unserved': [{'request_id': request.id, 'reasons': ['solver_failed']} for request in item.requests],
                'served_count': 0, 'total_pickup_seconds': 0, 'constraints_checked': False}
    assignments, covered, total_cost = [], set(), 0
    for arc, (i, j) in edge_arcs.items():
        if solver.flow(arc):
            cost, energy = eligible[i, j]
            assignments.append({'vehicle_id': item.vehicles[i].id, 'request_id': item.requests[j].id,
                                'pickup_duration_s': item.duration_matrix_s[i][j],
                                'pickup_distance_m': item.distance_matrix_m[i][j], 'energy': check_energy(energy)})
            covered.add(j)
            total_cost += cost
    unserved = []
    for j, request in enumerate(item.requests):
        if j not in covered:
            reasons = (['assignment_capacity_unavailable'] if any(edge[1] == j for edge in eligible)
                       else sorted(failures[j]) or ['no_vehicles'])
            unserved.append({'request_id': request.id, 'reasons': reasons})
    return {**common, 'status': 'OPTIMAL', 'assignments': sorted(assignments, key=lambda a: a['request_id']),
            'unserved': unserved, 'served_count': len(assignments), 'total_pickup_seconds': total_cost,
            'constraints_checked': True}
