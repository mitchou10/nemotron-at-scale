"""API errors, shaped like OpenAI's: {"error": {"message": ..., "type": ...}}."""


class ApiError(Exception):
    def __init__(
        self, message: str, status_code: int = 400, error_type: str = "invalid_request_error"
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type


def error_body(message: str, error_type: str = "invalid_request_error") -> dict[str, object]:
    return {"error": {"message": message, "type": error_type}}
