"""
Formatting nodes for LangGraph v3 workflows.

These nodes provide output formatting functionality for different
output types including text responses, visualizations, and exports.

All nodes follow LangGraph conventions:
- Nodes are callable objects (implement __call__)
- Nodes take state and return state updates
- Nodes are configurable through constructor parameters
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from langgraph.types import RunnableConfig

from graph_kb_api.flows.v3.state.common import BaseCommandState
from graph_kb_api.utils.enhanced_logger import EnhancedLogger

logger = EnhancedLogger(__name__)


class OutputFormat(Enum):
    """Supported output formats."""
    MARKDOWN = "markdown"
    HTML = "html"
    JSON = "json"
    PLAIN_TEXT = "plain_text"
    MERMAID = "mermaid"
    PLANTUML = "plantuml"


class ResponseFormattingNode:
    """
    Formats text responses for presentation to the user.

    Handles formatting of LLM responses, search results, and other
    text-based outputs in various formats (markdown, HTML, JSON, plain text).

    Configuration:
        default_format: Default output format if not specified in state
        content_fields: Fields to check for content (in priority order)

    Example:
        >>> node = ResponseFormattingNode(default_format='markdown')
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_format: str = 'markdown',
        content_fields: Optional[List[str]] = None
    ):
        """
        Initialize response formatting node.

        Args:
            default_format: Default output format
            content_fields: Fields to check for content (in priority order)
        """
        self.node_name = "response_formatting"
        self.default_format = default_format
        self.content_fields = content_fields or [
            'llm_response',
            'generated_content',
            'response_content'
        ]

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Format a text response.

        Args:
            state: Current workflow state
            config: LangGraph config

        Returns:
            State updates with formatted response
        """
        logger.info("Formatting response")

        # Get content to format
        content = self._get_content(state)

        if not content:
            logger.warning("No content to format")
            return {
                'formatted_response': '',
                'formatting_skipped': True,
                'formatting_reason': 'no_content'
            }

        # Get desired format
        output_format = state.get('output_format', self.default_format)

        try:
            # Format based on output type
            if output_format == 'markdown':
                formatted = self._format_as_markdown(content, state)
            elif output_format == 'html':
                formatted = self._format_as_html(content, state)
            elif output_format == 'json':
                formatted = self._format_as_json(content, state)
            elif output_format == 'plain_text':
                formatted = self._format_as_plain_text(content, state)
            else:
                # Default to markdown
                formatted = self._format_as_markdown(content, state)

            logger.info(f"Response formatted as {output_format}")

            return {
                'formatted_response': formatted,
                'response_format': output_format,
                'formatting_complete': True
            }

        except Exception as e:
            logger.error(f"Response formatting failed: {e}")
            # Return unformatted content as fallback
            return {
                'formatted_response': str(content),
                'response_format': 'plain_text',
                'formatting_failed': True,
                'formatting_error': str(e)
            }

    def _get_content(self, state: BaseCommandState) -> Any:
        """
        Get content to format from state.

        Args:
            state: Current workflow state

        Returns:
            Content to format, or None if not found
        """
        for field in self.content_fields:
            content = state.get(field)
            if content:
                return content
        return None

    def _format_as_markdown(self, content: Any, state: BaseCommandState) -> str:
        """Format content as Markdown."""
        if isinstance(content, str):
            return content
        elif isinstance(content, dict):
            # Format dictionary as markdown sections
            lines = []
            for key, value in content.items():
                lines.append(f"## {key.replace('_', ' ').title()}")
                lines.append(str(value))
                lines.append("")
            return "\n".join(lines)
        else:
            return str(content)

    def _format_as_html(self, content: Any, state: BaseCommandState) -> str:
        """Format content as HTML."""
        if isinstance(content, str):
            # Simple markdown-to-HTML conversion
            html = content.replace('\n\n', '</p><p>')
            html = html.replace('\n', '<br>')
            return f"<div><p>{html}</p></div>"
        else:
            return f"<pre>{str(content)}</pre>"

    def _format_as_json(self, content: Any, state: BaseCommandState) -> str:
        """Format content as JSON."""
        import json

        if isinstance(content, (dict, list)):
            return json.dumps(content, indent=2)
        elif isinstance(content, str):
            # Try to parse as JSON first
            try:
                parsed = json.loads(content)
                return json.dumps(parsed, indent=2)
            except:
                # Wrap string in JSON
                return json.dumps({'content': content}, indent=2)
        else:
            return json.dumps({'content': str(content)}, indent=2)

    def _format_as_plain_text(self, content: Any, state: BaseCommandState) -> str:
        """Format content as plain text."""
        return str(content)


class VisualizationFormattingNode:
    """
    Formats visualization data for display.

    Handles formatting of diagrams, graphs, and other visual outputs
    in various formats (Mermaid, PlantUML, Graphviz).

    Configuration:
        default_viz_type: Default visualization type if not specified
        data_fields: Fields to check for visualization data

    Example:
        >>> node = VisualizationFormattingNode(default_viz_type='mermaid')
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_viz_type: str = 'mermaid',
        data_fields: Optional[List[str]] = None
    ):
        """
        Initialize visualization formatting node.

        Args:
            default_viz_type: Default visualization type
            data_fields: Fields to check for visualization data
        """
        self.node_name = "visualization_formatting"
        self.default_viz_type = default_viz_type
        self.data_fields = data_fields or ['visualization_data', 'mermaid_code']

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Format visualization data.

        Args:
            state: Current workflow state
            config: LangGraph config

        Returns:
            State updates with formatted visualization
        """
        logger.info("Formatting visualization")

        # Get visualization data
        viz_data = self._get_viz_data(state)

        if not viz_data:
            logger.warning("No visualization data to format")
            return {
                'formatted_visualization': None,
                'formatting_skipped': True,
                'formatting_reason': 'no_visualization_data'
            }

        # Get visualization type
        viz_type = state.get('visualization_type', self.default_viz_type)

        try:
            # Format based on visualization type
            if viz_type == 'mermaid':
                formatted = self._format_mermaid_diagram(viz_data, state)
            elif viz_type == 'plantuml':
                formatted = self._format_plantuml_diagram(viz_data, state)
            elif viz_type == 'graphviz':
                formatted = self._format_graphviz_diagram(viz_data, state)
            else:
                # Default to mermaid
                formatted = self._format_mermaid_diagram(viz_data, state)

            logger.info(f"Visualization formatted as {viz_type}")

            return {
                'formatted_visualization': formatted,
                'visualization_format': viz_type,
                'formatting_complete': True
            }

        except Exception as e:
            logger.error(f"Visualization formatting failed: {e}")
            return {
                'formatted_visualization': str(viz_data),
                'visualization_format': 'raw',
                'formatting_failed': True,
                'formatting_error': str(e)
            }

    def _get_viz_data(self, state: BaseCommandState) -> Any:
        """
        Get visualization data from state.

        Args:
            state: Current workflow state

        Returns:
            Visualization data, or None if not found
        """
        for field in self.data_fields:
            data = state.get(field)
            if data:
                return data
        return None

    def _format_mermaid_diagram(self, viz_data: Any, state: BaseCommandState) -> str:
        """Format Mermaid diagram."""
        if isinstance(viz_data, str):
            # Ensure it's wrapped in mermaid code block
            if not viz_data.strip().startswith('```mermaid'):
                return f"```mermaid\n{viz_data}\n```"
            return viz_data
        else:
            return f"```mermaid\n{str(viz_data)}\n```"

    def _format_plantuml_diagram(self, viz_data: Any, state: BaseCommandState) -> str:
        """Format PlantUML diagram."""
        if isinstance(viz_data, str):
            # Ensure it's wrapped in plantuml code block
            if not viz_data.strip().startswith('@startuml'):
                return f"@startuml\n{viz_data}\n@enduml"
            return viz_data
        else:
            return f"@startuml\n{str(viz_data)}\n@enduml"

    def _format_graphviz_diagram(self, viz_data: Any, state: BaseCommandState) -> str:
        """Format Graphviz diagram."""
        if isinstance(viz_data, str):
            return viz_data
        else:
            return str(viz_data)


class ExportFormattingNode:
    """
    Formats data for export in various formats.

    Handles formatting of data for file export, API responses, etc.
    in various formats (JSON, CSV, Markdown, HTML).

    Configuration:
        default_export_format: Default export format if not specified
        data_fields: Fields to check for export data
        formatters: Custom formatters for specific formats

    Example:
        >>> node = ExportFormattingNode(default_export_format='json')
        >>> result = await node(state, config)
    """

    def __init__(
        self,
        default_export_format: str = 'json',
        data_fields: Optional[List[str]] = None,
        formatters: Optional[Dict[str, callable]] = None
    ):
        """
        Initialize export formatting node.

        Args:
            default_export_format: Default export format
            data_fields: Fields to check for export data
            formatters: Custom formatters for specific formats
        """
        self.node_name = "export_formatting"
        self.default_export_format = default_export_format
        self.data_fields = data_fields or ['export_data', 'final_output']
        self.formatters = formatters or {}

    async def __call__(
        self,
        state: BaseCommandState,
        config: Optional[RunnableConfig] = None
    ) -> Dict[str, Any]:
        """
        Format data for export.

        Args:
            state: Current workflow state
            config: LangGraph config

        Returns:
            State updates with formatted export data
        """
        logger.info("Formatting export data")

        # Get data to export
        export_data = self._get_export_data(state)

        if not export_data:
            logger.warning("No data to export")
            return {
                'formatted_export': None,
                'formatting_skipped': True,
                'formatting_reason': 'no_export_data'
            }

        # Get export format
        export_format = state.get('export_format', self.default_export_format)

        try:
            # Check for custom formatter first
            if export_format in self.formatters:
                formatted = self.formatters[export_format](export_data, state)
            # Format based on export type
            elif export_format == 'json':
                formatted = self._format_export_json(export_data, state)
            elif export_format == 'csv':
                formatted = self._format_export_csv(export_data, state)
            elif export_format == 'markdown':
                formatted = self._format_export_markdown(export_data, state)
            elif export_format == 'html':
                formatted = self._format_export_html(export_data, state)
            else:
                # Default to JSON
                formatted = self._format_export_json(export_data, state)

            logger.info(f"Export data formatted as {export_format}")

            return {
                'formatted_export': formatted,
                'export_format': export_format,
                'formatting_complete': True
            }

        except Exception as e:
            logger.error(f"Export formatting failed: {e}")
            return {
                'formatted_export': str(export_data),
                'export_format': 'plain_text',
                'formatting_failed': True,
                'formatting_error': str(e)
            }

    def _get_export_data(self, state: BaseCommandState) -> Any:
        """
        Get export data from state.

        Args:
            state: Current workflow state

        Returns:
            Export data, or None if not found
        """
        for field in self.data_fields:
            data = state.get(field)
            if data:
                return data
        return None

    def _format_export_json(self, data: Any, state: BaseCommandState) -> str:
        """Format data as JSON for export."""
        import json
        return json.dumps(data, indent=2, default=str)

    def _format_export_csv(self, data: Any, state: BaseCommandState) -> str:
        """Format data as CSV for export."""
        import csv
        import io

        output = io.StringIO()

        if isinstance(data, list) and data and isinstance(data[0], dict):
            # List of dictionaries - use keys as headers
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        elif isinstance(data, dict):
            # Single dictionary - two columns (key, value)
            writer = csv.writer(output)
            writer.writerow(['Key', 'Value'])
            for key, value in data.items():
                writer.writerow([key, str(value)])
        else:
            # Fallback - single column
            writer = csv.writer(output)
            writer.writerow(['Data'])
            writer.writerow([str(data)])

        return output.getvalue()

    def _format_export_markdown(self, data: Any, state: BaseCommandState) -> str:
        """Format data as Markdown for export."""
        if isinstance(data, str):
            return data
        elif isinstance(data, dict):
            # Format dictionary as markdown sections
            lines = []
            for key, value in data.items():
                lines.append(f"## {key.replace('_', ' ').title()}")
                lines.append(str(value))
                lines.append("")
            return "\n".join(lines)
        else:
            return str(data)

    def _format_export_html(self, data: Any, state: BaseCommandState) -> str:
        """Format data as HTML for export."""
        if isinstance(data, str):
            # Simple markdown-to-HTML conversion
            html = data.replace('\n\n', '</p><p>')
            html = html.replace('\n', '<br>')
            return f"<div><p>{html}</p></div>"
        else:
            return f"<pre>{str(data)}</pre>"
