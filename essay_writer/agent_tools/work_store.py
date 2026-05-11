from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from essay_writer.agent_tools.id_utils import content_hash, safe_slug, short_hash
from essay_writer.agent_tools.json_io import list_json_files, read_json, write_json_atomic
from essay_writer.agent_tools.schemas import (
    CommitRecord,
    SourcePacketBundle,
    WorkPacket,
    WorkProducer,
    WorkResult,
)


class AgentWorkStore:
    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.packets_dir = self.base_dir / "packets"
        self.results_dir = self.base_dir / "results"
        self.commits_dir = self.base_dir / "commits"
        self.source_packet_bundles_dir = self.base_dir / "source_packet_bundles"
        for directory in (
            self.packets_dir,
            self.results_dir,
            self.commits_dir,
            self.source_packet_bundles_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def save_packet(self, packet: WorkPacket) -> WorkPacket:
        write_json_atomic(self.packets_dir / f"{packet.work_packet_id}.json", asdict(packet))
        return packet

    def load_packet(self, work_packet_id: str) -> WorkPacket:
        return WorkPacket.from_dict(read_json(self.packets_dir / f"{work_packet_id}.json"))

    def list_packets(
        self,
        *,
        scope: str | None = None,
        status: str | None = None,
    ) -> list[WorkPacket]:
        packets = [WorkPacket.from_dict(read_json(path)) for path in list_json_files(self.packets_dir)]
        if scope is not None:
            packets = [packet for packet in packets if packet.scope == scope]
        if status is not None:
            packets = [packet for packet in packets if packet.status == status]
        return sorted(packets, key=lambda packet: (packet.created_at, packet.work_packet_id))

    def submit_result(
        self,
        work_packet_id: str,
        *,
        payload: dict[str, object],
        producer: WorkProducer,
        warnings: list[str] | None = None,
    ) -> WorkResult:
        self.load_packet(work_packet_id)
        payload_digest = content_hash(payload)
        result_id = f"workres_{safe_slug(work_packet_id)}_{short_hash(payload)}"
        path = self.results_dir / f"{result_id}.json"
        if path.exists():
            existing = WorkResult.from_dict(read_json(path))
            if existing.payload_hash == payload_digest:
                return existing
            result_id = (
                f"workres_{safe_slug(work_packet_id)}_"
                f"{payload_digest.split(':', 1)[1]}"
            )
            path = self.results_dir / f"{result_id}.json"
            if path.exists():
                existing = WorkResult.from_dict(read_json(path))
                if existing.payload_hash == payload_digest:
                    return existing
                raise ValueError(f"work result hash collision for {work_packet_id}")
        result = WorkResult(
            work_result_id=result_id,
            work_packet_id=work_packet_id,
            status="submitted",
            producer=producer,
            payload=payload,
            payload_hash=payload_digest,
            warnings=list(warnings or []),
        )
        write_json_atomic(path, asdict(result))
        return result

    def load_result(self, work_result_id: str) -> WorkResult:
        return WorkResult.from_dict(read_json(self.results_dir / f"{work_result_id}.json"))

    def list_results(
        self,
        *,
        scope: str | None = None,
        status: str | None = None,
    ) -> list[WorkResult]:
        results = [WorkResult.from_dict(read_json(path)) for path in list_json_files(self.results_dir)]
        if status is not None:
            results = [result for result in results if result.status == status]
        if scope is not None:
            scoped_results = []
            for result in results:
                try:
                    packet = self.load_packet(result.work_packet_id)
                except FileNotFoundError:
                    continue
                if packet.scope == scope:
                    scoped_results.append(result)
            results = scoped_results
        return sorted(results, key=lambda result: (result.created_at, result.work_result_id))

    def save_commit(
        self,
        *,
        scope: str,
        stage: str,
        work_packet_id: str,
        work_result_id: str,
        artifact_refs: dict[str, object],
    ) -> CommitRecord:
        artifact_hash = short_hash(artifact_refs)
        commit_id = (
            f"commit_{safe_slug(scope)}_{safe_slug(stage)}_"
            f"{safe_slug(work_result_id)}_{artifact_hash}"
        )
        path = self.commits_dir / f"{commit_id}.json"
        if path.exists():
            existing = CommitRecord.from_dict(read_json(path))
            if (
                existing.scope == scope
                and existing.stage == stage
                and existing.work_packet_id == work_packet_id
                and existing.work_result_id == work_result_id
                and existing.artifact_refs == artifact_refs
            ):
                return existing
            raise ValueError(f"commit id collision for {commit_id}")
        commit = CommitRecord(
            commit_id=commit_id,
            scope=scope,
            stage=stage,
            work_packet_id=work_packet_id,
            work_result_id=work_result_id,
            artifact_refs=artifact_refs,
        )
        write_json_atomic(path, asdict(commit))
        return commit

    def load_commit(self, commit_id: str) -> CommitRecord:
        return CommitRecord.from_dict(read_json(self.commits_dir / f"{commit_id}.json"))

    def list_commits(
        self,
        *,
        scope: str | None = None,
        stage: str | None = None,
    ) -> list[CommitRecord]:
        commits = [CommitRecord.from_dict(read_json(path)) for path in list_json_files(self.commits_dir)]
        if scope is not None:
            commits = [commit for commit in commits if commit.scope == scope]
        if stage is not None:
            commits = [commit for commit in commits if commit.stage == stage]
        return sorted(commits, key=lambda commit: (commit.created_at, commit.commit_id))

    def save_source_packet_bundle(self, bundle: SourcePacketBundle) -> SourcePacketBundle:
        write_json_atomic(
            self.source_packet_bundles_dir / f"{bundle.source_packet_bundle_id}.json",
            asdict(bundle),
        )
        return bundle

    def load_source_packet_bundle(self, source_packet_bundle_id: str) -> SourcePacketBundle:
        return SourcePacketBundle.from_dict(
            read_json(self.source_packet_bundles_dir / f"{source_packet_bundle_id}.json")
        )
