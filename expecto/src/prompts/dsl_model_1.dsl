predicate spec(n: int, k: int, s: int, t: int, cars: list[tuple[int, int]], gas_stations: list[int], output: int) {
    var all_stops: list[int] := sort(concat(gas_stations, [0, s]));
    var segments: list[int] := calculate_segments(all_stops);
    var suitable_cars: list[tuple[int, int]] := filter(lambda (car) = is_suitable(car[1], t, segments), cars);

    if len(suitable_cars) == 0 then
        output == -1
    else
        output == min(map(lambda (car) = car[0], suitable_cars))
}

function sort(arr: list[int]) -> (res: list[int]) {
    ensure is_sorted(res) ∧ is_permutation(res, arr);
}

predicate is_sorted(arr: list[int]) {
    var length: int := len(arr);
    ∀ (i) :: 0 <= i < length - 1 ==> arr[i] <= arr[i+1]
}

predicate is_permutation(l1: list[int], l2: list[int]) {
    list2multiset(l1) == list2multiset(l2)
}

function calculate_segments(sorted_stops: list[int]) -> list[int] {
    var n: int := len(sorted_stops);
    var diffs_with_extra: list[int] := map_i(lambda (i, stop) =
        if i < n - 1 then sorted_stops[i+1] - stop else 0,
        sorted_stops
    );
    substr(diffs_with_extra, 0, n - 1)
}

predicate is_suitable(car_capacity: int, t: int, segments: list[int]) {
    var max_segment_length: int := max(segments);
    (car_capacity >= max_segment_length) ∧ (min_total_travel_time(car_capacity, segments) <= t)
}

function min_total_travel_time(v: int, segments: list[int]) -> int {
    sum(map(lambda (d) = min_time_for_segment(d, v), segments))
}

function min_time_for_segment(d: int, v: int) -> int {
    if v >= 2 * d then d else 3 * d - v
}