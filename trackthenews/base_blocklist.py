from abc import ABC, abstractmethod


class BaseBlocklist(ABC):
    """Abstract base class for blocklists."""

    @abstractmethod
    def check_article(self, article):
        """Check if an entire article should be blocked."""
        pass

    @abstractmethod
    def check_paragraph(self, article, paragraph):
        """Check if an otherwise matchign paragraph should be blocked based on its content."""
        pass
