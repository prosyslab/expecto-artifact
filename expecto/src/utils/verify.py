from inspect_ai.solver import TaskState


def calc_communication_length(state: TaskState) -> int:
    """
    Calculate the communication length of the task state
    """
    return len(state.messages)
