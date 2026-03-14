predicate spec(n: int, arr: list[int], output: int){
    var N: int := len(arr);
    ((n == N) ∧
        (∃(S) ::
            (valid_choice_set(arr, S) ∧
                (sum_selected(arr, S) == output))))
}

predicate valid_choice_set(arr: list[int], S: set[int]){
    ((∀(i) ::
        ((i in S) ==>
            ((0 <= i) ∧
                (i < len(arr))))) ∧
        (∀(i, j) ::
            (((i in S) ∧
                (j in S)) ==>
                ((arr[i] != (arr[j] +
                    1)) ∧
                    (arr[i] != (arr[j] -
                        1))))))
}

function sum_selected(arr: list[int], S: set[int]) -> int {
    sum(map_i(lambda (i, x) =
        (if (i in S) then x else 0), arr))
}
