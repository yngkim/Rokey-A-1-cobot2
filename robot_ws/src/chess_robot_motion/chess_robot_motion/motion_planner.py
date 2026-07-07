"""Z-first Cartesian motion helpers for Doosan pick-and-place."""

from __future__ import annotations

from typing import Callable, Protocol


class SquarePoseMap(Protocol):
    z_pick_mm: float
    z_travel_mm: float
    fixed_orientation: list[float]

    def square_center_xy(self, col: int, row: int) -> tuple[float, float]: ...


class ZFirstMotionPlanner:
    """Travel-Z maintained XY moves, then pick/place Z dips."""

    def __init__(
        self,
        pose_map: SquarePoseMap,
        movel: Callable,
        mwait: Callable,
        get_current_posx: Callable,
        velocity: float = 120.0,
        acceleration: float = 120.0,
        pick_velocity: float = 80.0,
        pick_acceleration: float = 80.0,
        place_velocity: float = 35.0,
        place_acceleration: float = 35.0,
        retreat_velocity: float = 60.0,
        retreat_acceleration: float = 60.0,
        z_approach_offset_mm: float = 25.0,
    ) -> None:
        self.pose_map = pose_map
        self.movel = movel
        self.mwait = mwait
        self.get_current_posx = get_current_posx
        self.velocity = velocity
        self.acceleration = acceleration
        self.pick_velocity = pick_velocity
        self.pick_acceleration = pick_acceleration
        self.place_velocity = place_velocity
        self.place_acceleration = place_acceleration
        self.retreat_velocity = retreat_velocity
        self.retreat_acceleration = retreat_acceleration
        self.z_approach_offset_mm = z_approach_offset_mm

    def _move(
        self,
        posx: list[float],
        *,
        vel: float | None = None,
        acc: float | None = None,
    ) -> None:
        self.movel(posx, vel=vel if vel is not None else self.velocity, acc=acc if acc is not None else self.acceleration)
        self.mwait()

    def _current_xyz(self) -> tuple[float, float, float]:
        pos = self.get_current_posx()[0]
        return float(pos[0]), float(pos[1]), float(pos[2])

    def _ori(self) -> list[float]:
        return self.pose_map.fixed_orientation

    def _pmap(self, pose_map: SquarePoseMap | None) -> SquarePoseMap:
        return pose_map if pose_map is not None else self.pose_map

    def _ori_from(self, pose_map: SquarePoseMap | None) -> list[float]:
        return self._pmap(pose_map).fixed_orientation

    def ensure_travel_height(self, pose_map: SquarePoseMap | None = None) -> None:
        """Keep XY, raise/maintain Z at travel height."""
        pmap = self._pmap(pose_map)
        cur_x, cur_y, _ = self._current_xyz()
        self._move([cur_x, cur_y, pmap.z_travel_mm, *pmap.fixed_orientation])

    def move_xy_at_travel(self, col: int, row: int, pose_map: SquarePoseMap | None = None) -> None:
        """Move XY at travel Z (Z unchanged)."""
        pmap = self._pmap(pose_map)
        target_x, target_y = pmap.square_center_xy(col, row)
        self._move([target_x, target_y, pmap.z_travel_mm, *pmap.fixed_orientation])

    def _descend_to_z(
        self,
        z_target: float,
        *,
        approach_vel: float,
        approach_acc: float,
        final_vel: float,
        final_acc: float,
        pose_map: SquarePoseMap | None = None,
        use_approach_split: bool = False,
    ) -> None:
        """Lower Z in one smooth move, or split only when use_approach_split is set."""
        ori = self._ori_from(pose_map)
        cur_x, cur_y, cur_z = self._current_xyz()
        approach_z = z_target + self.z_approach_offset_mm
        if use_approach_split and self.z_approach_offset_mm > 0.5 and cur_z > approach_z + 0.5:
            self._move([cur_x, cur_y, approach_z, *ori], vel=approach_vel, acc=approach_acc)
            cur_x, cur_y, _ = self._current_xyz()
            self._move([cur_x, cur_y, z_target, *ori], vel=final_vel, acc=final_acc)
            return
        self._move([cur_x, cur_y, z_target, *ori], vel=final_vel, acc=final_acc)

    def descend_to_pick(self, pose_map: SquarePoseMap | None = None) -> None:
        """Lower Z to pick height at current XY."""
        pmap = self._pmap(pose_map)
        self._descend_to_z(
            pmap.z_pick_mm,
            approach_vel=self.pick_velocity,
            approach_acc=self.pick_acceleration,
            final_vel=self.pick_velocity,
            final_acc=self.pick_acceleration,
            pose_map=pose_map,
            use_approach_split=False,
        )

    def descend_to_place(self, pose_map: SquarePoseMap | None = None) -> None:
        """Lower Z to place height (single smooth descent)."""
        pmap = self._pmap(pose_map)
        self._descend_to_z(
            pmap.z_pick_mm,
            approach_vel=self.pick_velocity,
            approach_acc=self.pick_acceleration,
            final_vel=self.place_velocity,
            final_acc=self.place_acceleration,
            pose_map=pose_map,
            use_approach_split=False,
        )

    def ascend_to_travel(self, *, slow: bool = False, pose_map: SquarePoseMap | None = None) -> None:
        """Lift Z back to travel height at current XY."""
        pmap = self._pmap(pose_map)
        cur_x, cur_y, _ = self._current_xyz()
        if slow:
            self._move(
                [cur_x, cur_y, pmap.z_travel_mm, *pmap.fixed_orientation],
                vel=self.retreat_velocity,
                acc=self.retreat_acceleration,
            )
        else:
            self._move([cur_x, cur_y, pmap.z_travel_mm, *pmap.fixed_orientation])

    def pick_and_place_path(
        self,
        from_col: int,
        from_row: int,
        to_col: int,
        to_row: int,
        close_gripper: Callable[[], None],
        open_gripper: Callable[[], None],
    ) -> None:
        """Full pick-place: travel Z, XY, down/up cycle twice, Z maintained on XY legs."""
        self.ensure_travel_height()

        self.move_xy_at_travel(from_col, from_row)
        self.descend_to_pick()
        close_gripper()
        self.ascend_to_travel()

        self.move_xy_at_travel(to_col, to_row)
        self.descend_to_place()
        open_gripper()
        self.ascend_to_travel(slow=True)

    def pick_piece_at(
        self,
        col: int,
        row: int,
        close_gripper: Callable[[], None],
        pose_map: SquarePoseMap | None = None,
    ) -> None:
        """Pick up a piece at square without placing elsewhere (Z-first)."""
        self.ensure_travel_height(pose_map)
        self.move_xy_at_travel(col, row, pose_map)
        self.descend_to_pick(pose_map)
        close_gripper()
        self.ascend_to_travel(pose_map=pose_map)

    def place_piece_at(
        self,
        col: int,
        row: int,
        open_gripper: Callable[[], None],
        pose_map: SquarePoseMap | None = None,
    ) -> None:
        """Place held piece at square using Z-first motion (optional alternate pose map)."""
        self.ensure_travel_height(pose_map)
        self.move_xy_at_travel(col, row, pose_map)
        self.descend_to_place(pose_map)
        open_gripper()
        self.ascend_to_travel(slow=False, pose_map=pose_map)

    def place_at_current_xy(
        self,
        open_gripper: Callable[[], None],
        pose_map: SquarePoseMap | None = None,
    ) -> None:
        """Place held piece at current XY (no horizontal move)."""
        self.descend_to_place(pose_map)
        open_gripper()
        self.ascend_to_travel(slow=False, pose_map=pose_map)

    # Backward-compatible helpers
    def lift_to_travel(self) -> None:
        self.ensure_travel_height()

    def move_z_then_xy_then_z(
        self,
        target_col: int,
        target_row: int,
        z_final: float,
    ) -> None:
        del z_final
        self.ensure_travel_height()
        self.move_xy_at_travel(target_col, target_row)
        self.descend_to_pick()
