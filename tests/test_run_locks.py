from __future__ import annotations

import unittest

from research_digest.run_locks import (
    ProcessRunOwner,
    RunOwnerState,
    process_run_owner_state,
)


class RunLockOwnerTests(unittest.TestCase):
    def test_matching_process_identity_is_alive(self) -> None:
        owner = ProcessRunOwner(
            pid=123,
            host="host-a",
            start_ticks=456,
            nonce="nonce",
        ).to_owner_string()

        state = process_run_owner_state(
            owner,
            current_host="host-a",
            start_ticks_reader=lambda _pid: 456,
        )

        self.assertEqual(state, RunOwnerState.ALIVE)

    def test_missing_process_is_dead(self) -> None:
        owner = ProcessRunOwner(
            pid=123,
            host="host-a",
            start_ticks=456,
            nonce="nonce",
        ).to_owner_string()

        state = process_run_owner_state(
            owner,
            current_host="host-a",
            start_ticks_reader=lambda _pid: None,
        )

        self.assertEqual(state, RunOwnerState.DEAD)

    def test_pid_reuse_with_different_start_time_is_dead(self) -> None:
        owner = ProcessRunOwner(
            pid=123,
            host="host-a",
            start_ticks=456,
            nonce="nonce",
        ).to_owner_string()

        state = process_run_owner_state(
            owner,
            current_host="host-a",
            start_ticks_reader=lambda _pid: 789,
        )

        self.assertEqual(state, RunOwnerState.DEAD)

    def test_legacy_owner_is_unknown(self) -> None:
        self.assertEqual(
            process_run_owner_state("pid:legacy-uuid", current_host="host-a"),
            RunOwnerState.UNKNOWN,
        )

    def test_different_host_is_unknown(self) -> None:
        owner = ProcessRunOwner(
            pid=123,
            host="host-b",
            start_ticks=456,
            nonce="nonce",
        ).to_owner_string()

        state = process_run_owner_state(
            owner,
            current_host="host-a",
            start_ticks_reader=lambda _pid: 456,
        )

        self.assertEqual(state, RunOwnerState.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
