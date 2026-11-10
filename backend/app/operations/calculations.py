"""Decimal arithmetic over explicit assumptions; these tools never move money."""
from decimal import Decimal, ROUND_HALF_UP
from heapq import heapify, heapreplace

from .models import FareInput, RefundInput, EnergyInput, ChargeInput

FARE_POLICY = {
    'id': 'safejourney-demo-v1', 'currency': 'VND', 'base_vnd': '15000',
    'per_km_vnd': '10000', 'per_minute_vnd': '500', 'waiting_per_minute_vnd': '500',
    'rounding': 'ROUND_HALF_UP_TO_1_VND', 'simulated': True,
}


def decimal_text(value, places='0.000001'):
    return format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), 'f')


def quote_fare(value: FareInput | dict) -> dict:
    item = FareInput.model_validate(value)
    distance = item.distance_m / 1000 * Decimal(FARE_POLICY['per_km_vnd'])
    travel = item.duration_s / 60 * Decimal(FARE_POLICY['per_minute_vnd'])
    waiting = item.waiting_s / 60 * Decimal(FARE_POLICY['waiting_per_minute_vnd'])
    base = Decimal(FARE_POLICY['base_vnd'])
    before_discount = base + distance + travel + waiting + item.surcharge_vnd
    discount = min(before_discount, item.discount_vnd)
    total = (before_discount-discount).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return {'policy': dict(FARE_POLICY), 'total_vnd': str(total), 'components_vnd': {
        'base': str(base), 'distance': decimal_text(distance), 'travel_time': decimal_text(travel),
        'waiting_time': decimal_text(waiting), 'surcharge': decimal_text(item.surcharge_vnd),
        'discount_applied': decimal_text(discount)},
        'input': item.model_dump(mode='json'), 'calculation_verified': True,
        'assumptions': ['Biểu giá minh họa, không phải cước hợp đồng hoặc cước NYC TLC.',
                        'duration_s chỉ tính thời gian di chuyển; waiting_s là thời gian chờ bổ sung.'],
        'money_moved': False}


def calculate_refund(value: RefundInput | dict) -> dict:
    item = RefundInput.model_validate(value)
    remaining = item.paid_vnd-item.already_refunded_vnd
    refund = min(remaining, max(Decimal(0), item.paid_vnd-item.expected_vnd-item.already_refunded_vnd))
    # Round down so a fractional paid amount cannot be over-refunded by rounding.
    from decimal import ROUND_DOWN
    refund = refund.quantize(Decimal(1), rounding=ROUND_DOWN)
    return {'policy': 'safejourney-demo-refund-v1', 'currency': 'VND',
            'refund_vnd': str(refund), 'remaining_refundable_vnd': decimal_text(remaining),
            'input': item.model_dump(mode='json'), 'calculation_verified': True, 'money_moved': False,
            'assumptions': ['Chỉ tính phần chênh đã thu sau khi trừ khoản đã hoàn; không kết luận gian lận.',
                            'Đây là báo giá hoàn tiền mô phỏng; không tạo giao dịch thanh toán.']}


def energy_values(item: EnergyInput):
    """Keep full Decimal precision for eligibility; format only at the boundary."""
    profile = item.profile
    usable = profile.capacity_kwh * profile.soh_percent / 100
    current = usable * profile.soc_percent / 100
    reserve = usable * profile.reserve_percent / 100
    required = (item.distance_m * profile.consumption_wh_per_km / 1_000_000
                + item.duration_s * profile.auxiliary_kw / 3600)
    return usable, current, reserve, required


def check_energy(value: EnergyInput | dict) -> dict:
    item = EnergyInput.model_validate(value)
    usable, current, reserve, required = energy_values(item)
    margin = current-required-reserve
    return {'policy': 'linear-energy-v1', 'feasible': margin >= 0,
            'usable_capacity_kwh': decimal_text(usable), 'current_kwh': decimal_text(current),
            'required_kwh': decimal_text(required), 'available_kwh': decimal_text(max(Decimal(0), current-reserve)),
            'reserve_kwh': decimal_text(reserve), 'remaining_kwh': decimal_text(max(Decimal(0), current-required)),
            'margin_after_reserve_kwh': decimal_text(margin),
            'remaining_soc_percent': decimal_text(max(Decimal(0), (current-required)/usable*100)),
            'input': item.model_dump(mode='json'), 'calculation_verified': True,
            'assumptions': ['Mô hình tuyến tính theo Wh/km cộng phụ tải theo thời gian; dùng dung lượng nhân SOH.',
                            'Không phải dự báo thực nghiệm cho nhiệt độ, dốc đường, tái sinh hoặc suy hao pin.']}


def estimate_charge(value: ChargeInput | dict) -> dict:
    item = ChargeInput.model_validate(value)
    usable = item.profile.capacity_kwh * item.profile.soh_percent / 100
    required = usable * (item.target_soc_percent-item.profile.soc_percent) / 100
    power = min(item.station_power_kw, item.vehicle_max_power_kw) * item.efficiency
    charge_minutes = required/power*60
    free_at = list(item.busy_remaining_minutes)
    heapify(free_at)
    for _ in range(item.queue_length):
        heapreplace(free_at, free_at[0]+item.queue_session_minutes)
    wait = free_at[0] if required > 0 else Decimal(0)
    return {'policy': 'fcfs-constant-power-v1', 'wait_minutes': decimal_text(wait),
            'charge_minutes': decimal_text(charge_minutes), 'total_minutes': decimal_text(wait+charge_minutes),
            'energy_to_add_kwh': decimal_text(required), 'effective_power_kw': decimal_text(power),
            'input': item.model_dump(mode='json'), 'calculation_verified': True,
            'assumptions': ['Hàng chờ FCFS, cổng sạc tương đương, không có người mới chen hàng hoặc cổng hỏng.',
                            'Công suất hằng = min(trạm, xe) × hiệu suất; chưa mô hình hóa taper hoặc đặt chỗ.']}
