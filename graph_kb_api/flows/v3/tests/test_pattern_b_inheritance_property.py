"""Property-based tests for inheritance and node names (Pattern B nodes).

Property 1: Inheritance Contract
    Verify ``issubclass(ApprovalNode, BaseWorkflowNodeV3)`` and
    ``issubclass(HumanInputNode, BaseWorkflowNodeV3)``.

Property 2: Constructor and Node Name Contract
    Verify ``node.node_name`` matches ``"approval"`` and ``"human_input"``
    respectively after instantiation.

**Validates: Requirements 1.1, 1.2, 17.3, 17.4**
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from graph_kb_api.flows.v3.nodes.approval_node import ApprovalNode
from graph_kb_api.flows.v3.nodes.base_node import BaseWorkflowNodeV3
from graph_kb_api.flows.v3.nodes.human_input_node import HumanInputNode

# ---------------------------------------------------------------------------
# Property 1: Inheritance Contract
# ---------------------------------------------------------------------------


class TestInheritanceContract:
    """Property 1: Inheritance Contract.

    For Pattern B nodes (ApprovalNode, HumanInputNode),
    ``issubclass(NodeClass, BaseWorkflowNodeV3)`` must be ``True``.

    **Validates: Requirements 1.1, 17.3**
    """

    @given(data=st.just(None))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_approval_node_is_subclass(self, data):
        """ApprovalNode is a subclass of BaseWorkflowNodeV3."""
        assert issubclass(ApprovalNode, BaseWorkflowNodeV3)

    @given(data=st.just(None))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_human_input_node_is_subclass(self, data):
        """HumanInputNode is a subclass of BaseWorkflowNodeV3."""
        assert issubclass(HumanInputNode, BaseWorkflowNodeV3)

    @given(data=st.just(None))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_approval_node_isinstance(self, data):
        """ApprovalNode instance passes isinstance check."""
        node = ApprovalNode()
        assert isinstance(node, BaseWorkflowNodeV3)

    @given(data=st.just(None))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_human_input_node_isinstance(self, data):
        """HumanInputNode instance passes isinstance check."""
        node = HumanInputNode()
        assert isinstance(node, BaseWorkflowNodeV3)


# ---------------------------------------------------------------------------
# Property 2: Constructor and Node Name Contract
# ---------------------------------------------------------------------------


class TestNodeNameContract:
    """Property 2: Constructor and Node Name Contract.

    After instantiation, ``node.node_name`` must match the expected
    string for each Pattern B node.

    **Validates: Requirements 1.2, 17.4**
    """

    @given(data=st.just(None))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_approval_node_name(self, data):
        """ApprovalNode.node_name == 'approval'."""
        node = ApprovalNode()
        assert node.node_name == "approval"

    @given(data=st.just(None))
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_human_input_node_name(self, data):
        """HumanInputNode.node_name == 'human_input'."""
        node = HumanInputNode()
        assert node.node_name == "human_input"
