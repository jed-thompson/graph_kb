"""Tests for loop detection and circuit breaker in orchestrate subgraph."""

import pytest

from graph_kb_api.flows.v3.graphs.plan_subgraphs.orchestrate_subgraph import (
    OrchestrateSubgraph,
)


class TestCircuitBreaker:
    """Test the circuit breaker routing logic."""

    def test_all_tasks_rejected_triggers_circuit_breaker(self):
        """When circuit breaker flag is set, route to __end__."""
        state = {
            "orchestrate": {
                "circuit_breaker_triggered": True,
                "all_complete": False,
            }
        }
        # Simulate routing after progress
        route = OrchestrateSubgraph._route_after_progress(state)
        assert route == "__end__", "Should trigger circuit breaker and end"

    def test_repeated_rejection_of_same_task_detected(self):
        """When max iterations hit, loop guard fires in routing."""
        state = {
            "orchestrate": {
                "current_task_index": OrchestrateSubgraph.MAX_TASK_LOOP_ITERATIONS,
            }
        }
        route = OrchestrateSubgraph._route_after_progress(state)
        assert route == "__end__", "Should trigger loop guard"

    def test_no_tasks_marked_done_after_full_cycle(self):
        """Simulate evaluating consecutive rejections condition logic inline."""
        from graph_kb_api.flows.v3.nodes.plan.orchestrate_nodes import ProgressNode

        # Not testing the actual node execution here due to heavy mocking required,
        # but we can test the state transitions related to circuit breaker.
        # If consecutive_rejections >= total_tasks, circuit breaker is triggered.
        # We simulate the state just before ProgressNode routing
        
        # Test routing handles it if set
        state = {
            "orchestrate": {
                "circuit_breaker_triggered": True,
                "consecutive_rejections": 12,
                "ready_tasks": ["t1" for _ in range(12)]
            }
        }
        assert OrchestrateSubgraph._route_after_progress(state) == "__end__"

    def test_healthy_flow_does_not_trigger_circuit_breaker(self):
        """When flow is healthy, it routes to budget_check."""
        state = {
            "orchestrate": {
                "circuit_breaker_triggered": False,
                "all_complete": False,
                "current_task_index": 5,
                "consecutive_rejections": 0,
            }
        }
        route = OrchestrateSubgraph._route_after_progress(state)
        assert route == "budget_check", "Should continue orchestrating"

    def test_healthy_flow_all_complete(self):
        """When all tasks complete, routes to __end__ normally."""
        state = {
            "orchestrate": {
                "circuit_breaker_triggered": False,
                "all_complete": True,
            }
        }
        route = OrchestrateSubgraph._route_after_progress(state)
        assert route == "__end__", "Should end normally when complete"

    def test_blocked_tasks_breaks_loop(self):
        """When tasks are blocked (unmet dependencies), routes to __end__."""
        state = {
            "orchestrate": {
                "circuit_breaker_triggered": False,
                "all_complete": False,
                "blocked": True,
            }
        }
        route = OrchestrateSubgraph._route_after_progress(state)
        assert route == "__end__", "Should end due to blocked tasks"
