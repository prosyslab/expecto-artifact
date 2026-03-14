predicate spec(s: string, output: string){
    (((output == "YES") ∧
        has_non_overlapping_ab_ba(s)) ∨
        ((output == "NO") ∧
            (¬ has_non_overlapping_ab_ba(s))))
}

predicate has_non_overlapping_ab_ba(s: string){
    (∃(i, j) ::
        (((0 <= i < j < (len(s) - 1)) ∧
            ((contains_ab_at(s, i) ∧
                contains_ba_at(s, j)) ∨
                (contains_ba_at(s, i) ∧
                    contains_ab_at(s, j)))) ∧
            ((i + 2) <= j)))
}

predicate contains_ab_at(s: string, i: int){
    (((0 <= (i + 1) < len(s)) ∧
        (s[i] == 'A')) ∧
        (s[(i + 1)] == 'B'))
}


predicate contains_ba_at(s: string, j: int){
    (((0 <= (j + 1) < len(s)) ∧
        (s[j] == 'B')) ∧
        (s[(j + 1)] == 'A'))
}