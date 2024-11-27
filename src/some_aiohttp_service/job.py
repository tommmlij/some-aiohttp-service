from enum import Enum


class JobType(Enum):
    NORMAL = 1
    TERMINATE = 2


class Job:
    _current_id = -1

    type: JobType
    id: int
    data: dict
    config: dict
    repetitions: int

    @classmethod
    def _get_next_id(cls):
        cls._current_id += 1
        return cls._current_id

    def __init__(self, type: JobType = JobType.NORMAL, data: dict = dict, config: dict = dict):
        self.type = type
        self.id = self._get_next_id()
        self.data = data
        self.config = config
        self.repetitions = 0

    def __str__(self):
        return f"<Job id={self.id}>"

    def __repr__(self):
        return f"<Job id={self.id}>"
