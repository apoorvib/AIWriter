from essay_writer.tone_alignment.schema import ToneAlignmentConflict, ToneAlignmentReport

__all__ = [
    "ToneAlignmentConflict",
    "ToneAlignmentReport",
    "ToneAlignmentService",
    "ToneAlignmentStore",
]


def __getattr__(name: str):
    if name == "ToneAlignmentService":
        from essay_writer.tone_alignment.service import ToneAlignmentService

        return ToneAlignmentService
    if name == "ToneAlignmentStore":
        from essay_writer.tone_alignment.storage import ToneAlignmentStore

        return ToneAlignmentStore
    raise AttributeError(name)
