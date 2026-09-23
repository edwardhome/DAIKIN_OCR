class AppError(Exception):
    def __init__(self, code, message, status=400, retryable=False):
        super().__init__(message)
        self.code, self.message = code, message
        self.status, self.retryable = status, retryable


class ProviderError(AppError):
    def __init__(self, code, message, retryable=True):
        super().__init__(code, message, 502, retryable)
