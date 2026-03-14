from pydantic import BaseModel


class EvaluationResult(BaseModel):
    task_id: str
    assertion: str
    is_complete: bool
    is_sound: bool
    complete_ratio: float
    sound_ratio: float
    true_cnt_correct: int
    false_cnt_correct: int
    error_cnt_correct: int
    true_cnt_mutated: int
    false_cnt_mutated: int
    error_cnt_mutated: int
    msg_completeness: str
    msg_soundness: str


class AggregatedResult(BaseModel):
    exp_name: str
    sound_and_complete: int
    complete_only: int
    sound_only: int
    failed: int
    completeness_ratio: float
    soundness_ratio: float
    average_complete_ratio: float
    average_sound_ratio: float
