"""Custom exceptions for the optimization service."""


class OptimizationException(Exception):
    """Base exception for optimization service."""
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class InvalidPDVData(OptimizationException):
    """Raised when PDV data is invalid or incomplete."""
    def __init__(self, message: str = "Invalid PDV data"):
        super().__init__(message, status_code=400)


class InvalidCoordinates(OptimizationException):
    """Raised when latitude/longitude values are invalid."""
    def __init__(self, message: str = "Invalid coordinates"):
        super().__init__(message, status_code=400)


class FileSizeExceeded(OptimizationException):
    """Raised when uploaded file exceeds size limit."""
    def __init__(self, message: str = "File size exceeds 50MB limit"):
        super().__init__(message, status_code=413)


class RouteOptimizationError(OptimizationException):
    """Raised when route optimization fails."""
    def __init__(self, message: str = "Route optimization failed"):
        super().__init__(message, status_code=500)


class OSRMServiceError(OptimizationException):
    """Raised when OSRM service is unavailable."""
    def __init__(self, message: str = "Route service temporarily unavailable"):
        super().__init__(message, status_code=503)
