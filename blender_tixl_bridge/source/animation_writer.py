"""Bounded sequential batches within the existing record-major matrix cache."""

MATRIX_BYTES = 64
PAYLOAD_BUDGET = 8 * 1024 * 1024
MAX_BATCH_SAMPLES = 1024


def batch_samples(record_count):
    """Share a payload budget across records; a single sample writes directly."""
    return max(1, min(MAX_BATCH_SAMPLES,
                      PAYLOAD_BUDGET // max(1, record_count) // MATRIX_BYTES))


class MatrixRecordWriter:
    """Write one reserved record span; a write failure aborts the export."""

    def __init__(self, stream, offset, start, samples_per_batch):
        self.stream = stream
        self.offset = offset
        self.next_frame = start
        self.capacity = max(1, samples_per_batch) * MATRIX_BYTES
        self.buffer = bytearray()

    def append(self, frame, payload):
        if frame != self.next_frame or len(payload) != MATRIX_BYTES:
            raise ValueError("Matrix samples must be consecutive 64-byte records")
        if self.capacity == MATRIX_BYTES:
            self.stream.seek(self.offset)
            self.stream.write(payload)
            self.offset += MATRIX_BYTES
        else:
            self.buffer.extend(payload)
            if len(self.buffer) >= self.capacity:
                self.flush()
        self.next_frame += 1

    def flush(self):
        if self.buffer:
            self.stream.seek(self.offset)
            self.stream.write(self.buffer)
            self.offset += len(self.buffer)
            self.buffer.clear()
