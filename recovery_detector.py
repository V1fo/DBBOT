import os
import cv2
import numpy as np
from PIL import ImageGrab
import mss

class RecoveryDetector:
    def __init__(self, targets_dir: str = "targets"):
        self.targets_dir = targets_dir
        self.death_templates = {}
        self.disconnect_templates = {}
        self.server_reconnect_templates = {}
        self.lobby_templates = {}
        self.dungeon_templates = {}
        self.bottom_bar_templates = {}
        self._cached_bar_loc = None
        self._cached_scale = 1.0
        self._cached_game_rect = None
        self._sct = None
        self.reload_templates()

    def _get_sct(self):
        if self._sct is None:
            try:
                self._sct = mss.MSS()
            except Exception:
                self._sct = None
        return self._sct

    def close(self):
        if self._sct:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None

    def reload_templates(self):
        """Loads reference templates from targets directory."""
        self.death_templates = {}
        self.disconnect_templates = {}
        self.server_reconnect_templates = {}
        self.lobby_templates = {}
        self.dungeon_templates = {}
        self.bottom_bar_templates = {}
        self._cached_bar_loc = None
        self._cached_scale = 1.0
        self._cached_game_rect = None

        if not os.path.exists(self.targets_dir):
            os.makedirs(self.targets_dir, exist_ok=True)

        # Death / Angel templates
        for fname in ["revive_button.png", "angel_banner.png"]:
            path = os.path.join(self.targets_dir, fname)
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_COLOR)
                if img is not None:
                    self.death_templates[fname] = img

        # Disconnect / Lost Connection (in-game modal) templates
        for fname in ["refresh_button.png", "lost_connection_title.png"]:
            path = os.path.join(self.targets_dir, fname)
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_COLOR)
                if img is not None:
                    self.disconnect_templates[fname] = img

        # Server Reconnect (full disconnect screen) templates
        for fname in ["server_reconnect_btn.png", "server_reconnect_msg.png"]:
            path = os.path.join(self.targets_dir, fname)
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_COLOR)
                if img is not None:
                    self.server_reconnect_templates[fname] = img

        # Lobby / Town templates
        for fname in ["lobby_enter_btn.png", "lobby_banner.png"]:
            path = os.path.join(self.targets_dir, fname)
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_COLOR)
                if img is not None:
                    self.lobby_templates[fname] = img

        # Dungeon Complete / Exit Dungeon templates
        for fname in ["exit_dungeon_button.png", "dungeon_rank_ribbon.png"]:
            path = os.path.join(self.targets_dir, fname)
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_COLOR)
                if img is not None:
                    self.dungeon_templates[fname] = img

        # Bottom Bar & UI Anchors for HP & Skill detection
        for fname in ["hp_orb_anchor.png", "skill_bar_anchor.png", "empty_slots_anchor.png"]:
            path = os.path.join(self.targets_dir, fname)
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_COLOR)
                if img is not None:
                    self.bottom_bar_templates[fname] = img

    def capture_screen(self) -> np.ndarray:
        """Captures full screen as BGR numpy array using fast persistent MSS context."""
        sct = self._get_sct()
        if sct is not None:
            try:
                mon = sct.monitors[1]
                sct_img = sct.grab(mon)
                frame = np.asarray(sct_img)
                return frame[:, :, :3]
            except Exception:
                try:
                    sct.close()
                except Exception:
                    pass
                self._sct = None

        try:
            pil_img = ImageGrab.grab()
            rgb = np.array(pil_img)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        except Exception as e:
            raise RuntimeError(f"Failed to capture screen: {e}")

    def _match_templates(self, screen: np.ndarray, templates_dict: dict, threshold: float = 0.75, roi_box: tuple = None) -> tuple:
        """
        High performance template matching on game screen with optional ROI focusing.
        Directly matches native 1:1 templates with microsecond efficiency.
        Returns: (found: bool, best_score: float, best_loc: tuple, best_name: str)
        """
        if not templates_dict:
            return (False, 0.0, None, "No templates available")

        h, w = screen.shape[:2]
        if roi_box is not None:
            rx1, ry1, rx2, ry2 = roi_box
            if isinstance(rx1, float) and rx1 <= 1.0:
                rx1 = int(w * rx1)
                rx2 = int(w * rx2)
                ry1 = int(h * ry1)
                ry2 = int(h * ry2)
        else:
            rx1 = 0
            rx2 = w
            ry1 = int(h * 0.03) # Ignore top browser tabs/title
            ry2 = int(h * 0.97) # Ignore bottom taskbar

        rx1 = max(0, min(w - 1, rx1))
        rx2 = max(rx1 + 10, min(w, rx2))
        ry1 = max(0, min(h - 1, ry1))
        ry2 = max(ry1 + 10, min(h, ry2))

        roi = screen[ry1:ry2, rx1:rx2]
        best_score = 0.0
        best_loc = None
        best_name = None

        candidate_scales = [self._cached_scale, 1.0, 0.92, 0.95, 0.90, 0.88, 0.85, 1.05]
        scales = []
        for s in candidate_scales:
            s_val = round(float(s), 3)
            if s_val not in scales:
                scales.append(s_val)

        for name, template in templates_dict.items():
            th, tw = template.shape[:2]

            for s in scales:
                tw_s = int(tw * s)
                th_s = int(th * s)

                if th_s >= roi.shape[0] or tw_s >= roi.shape[1] or th_s < 5 or tw_s < 5:
                    continue

                t_scaled = cv2.resize(template, (tw_s, th_s), interpolation=cv2.INTER_LINEAR) if s != 1.0 else template
                res = cv2.matchTemplate(roi, t_scaled, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)

                if max_val > best_score:
                    best_score = float(max_val)
                    abs_x = rx1 + max_loc[0]
                    abs_y = ry1 + max_loc[1]
                    best_loc = (abs_x, abs_y, tw_s, th_s)
                    best_name = name

                if best_score >= threshold:
                    break

            if best_score >= 0.90:
                break

        found = best_score >= threshold
        return (found, best_score, best_loc, best_name)

    def check_death(self, screen: np.ndarray = None, threshold: float = 0.75) -> tuple:
        """Checks if Angel / Revive screen is visible."""
        if screen is None:
            screen = self.capture_screen()
        return self._match_templates(screen, self.death_templates, threshold=threshold, roi_box=(0.25, 0.18, 0.75, 0.82))

    def check_disconnect(self, screen: np.ndarray = None, threshold: float = 0.75) -> tuple:
        """Checks if Lost Connection dialog (in-game popup) is visible."""
        if screen is None:
            screen = self.capture_screen()
        return self._match_templates(screen, self.disconnect_templates, threshold=threshold, roi_box=(0.25, 0.18, 0.75, 0.82))

    def check_server_reconnect(self, screen: np.ndarray = None, threshold: float = 0.75) -> tuple:
        """Checks if Server Reconnect screen (full-client disconnection) is visible."""
        if screen is None:
            screen = self.capture_screen()
        return self._match_templates(screen, self.server_reconnect_templates, threshold=threshold, roi_box=(0.18, 0.35, 0.82, 0.85))

    def check_lobby(self, screen: np.ndarray = None, threshold: float = 0.75) -> tuple:
        """Checks if Town / Lobby screen is visible."""
        if screen is None:
            screen = self.capture_screen()
        return self._match_templates(screen, self.lobby_templates, threshold=threshold, roi_box=(0.45, 0.60, 0.95, 0.98))

    def check_dungeon_complete(self, screen: np.ndarray = None, threshold: float = 0.75) -> tuple:
        """Checks if Dungeon Complete / Exit Dungeon scoreboard is visible."""
        if screen is None:
            screen = self.capture_screen()
        return self._match_templates(screen, self.dungeon_templates, threshold=threshold, roi_box=(0.12, 0.45, 0.58, 0.88))

    def _update_cached_game_rect(self, ax: int, ay: int, scale: float, sw: int, sh: int):
        """Updates bounding box of the game canvas based on anchor position and scale."""
        gx1 = max(0, ax - int(60 * scale))
        gx2 = min(sw, ax + int(1360 * scale))
        gy1 = max(0, ay - int(760 * scale))
        gy2 = min(sh, ay + int(140 * scale))
        self._cached_game_rect = (gx1, gy1, gx2, gy2)

    def _find_bottom_bar_anchor(self, screen: np.ndarray) -> tuple:
        """
        Finds the bottom HUD bar anchor with multi-scale matching and fast local caching.
        Supports both Fullscreen (scale ~1.0) and Browser Window (scale ~0.92, 0.85, etc.).
        Returns: (matched: bool, score: float, scale: float, ax: int, ay: int)
        """
        anchor_tmpl = self.bottom_bar_templates.get("hp_orb_anchor.png")
        if anchor_tmpl is None:
            anchor_tmpl = self.bottom_bar_templates.get("skill_bar_anchor.png")
        if anchor_tmpl is None:
            anchor_tmpl = self.bottom_bar_templates.get("empty_slots_anchor.png")

        if anchor_tmpl is None:
            return (False, 0.0, 1.0, 0, 0)

        h, w = screen.shape[:2]
        roi_y = int(h * 0.48)  # Search bottom 52% of screen
        bottom = screen[roi_y:, :]
        bh, bw = bottom.shape[:2]

        # 1. Fast path: try cached location and cached scale
        if self._cached_bar_loc is not None:
            c_ax, c_ay = self._cached_bar_loc
            c_scale = self._cached_scale
            th = int(anchor_tmpl.shape[0] * c_scale)
            tw = int(anchor_tmpl.shape[1] * c_scale)

            pad_x = 45
            pad_y = 35
            x1 = max(0, c_ax - pad_x)
            x2 = min(w, c_ax + tw + pad_x)
            y1 = max(0, c_ay - roi_y - pad_y)
            y2 = min(bh, c_ay - roi_y + th + pad_y)

            if (x2 - x1 >= tw) and (y2 - y1 >= th):
                local_roi = bottom[y1:y2, x1:x2]
                t_scaled = cv2.resize(anchor_tmpl, (tw, th), interpolation=cv2.INTER_LINEAR) if abs(c_scale - 1.0) > 0.01 else anchor_tmpl
                res_local = cv2.matchTemplate(local_roi, t_scaled, cv2.TM_CCOEFF_NORMED)
                _, loc_max_v, _, loc_max_pt = cv2.minMaxLoc(res_local)
                if loc_max_v >= 0.70:
                    ax = x1 + loc_max_pt[0]
                    ay = roi_y + y1 + loc_max_pt[1]
                    self._cached_bar_loc = (ax, ay)
                    self._update_cached_game_rect(ax, ay, c_scale, w, h)
                    return (True, float(loc_max_v), c_scale, ax, ay)

        # 2. Multi-scale search on bottom region
        candidate_scales = [self._cached_scale, 1.0, 0.92, 0.95, 0.90, 0.88, 0.85, 0.82, 0.80, 1.05]
        tested_scales = []
        for s in candidate_scales:
            s_val = round(float(s), 3)
            if s_val not in tested_scales:
                tested_scales.append(s_val)

        best_v = 0.0
        best_scale = 1.0
        best_loc = (0, 0)

        for s in tested_scales:
            th = int(anchor_tmpl.shape[0] * s)
            tw = int(anchor_tmpl.shape[1] * s)
            if th >= bh or tw >= bw or th < 10 or tw < 10:
                continue

            t_scaled = cv2.resize(anchor_tmpl, (tw, th), interpolation=cv2.INTER_LINEAR) if abs(s - 1.0) > 0.01 else anchor_tmpl
            res = cv2.matchTemplate(bottom, t_scaled, cv2.TM_CCOEFF_NORMED)
            _, max_v, _, max_loc = cv2.minMaxLoc(res)
            if max_v > best_v:
                best_v = float(max_v)
                best_scale = s
                best_loc = (max_loc[0], roi_y + max_loc[1])

            if best_v >= 0.78:
                break

        if best_v >= 0.65:
            ax, ay = best_loc
            self._cached_bar_loc = (ax, ay)
            self._cached_scale = best_scale
            self._update_cached_game_rect(ax, ay, best_scale, w, h)
            return (True, best_v, best_scale, ax, ay)

        self._cached_bar_loc = None
        return (False, best_v, 1.0, 0, 0)

    def get_character_center(self, screen: np.ndarray = None) -> tuple:
        """
        Returns (char_x, char_y, scale) indicating the player character center in current view.
        Adapts dynamically between Fullscreen and Browser Window.
        """
        if self._cached_bar_loc is not None:
            ax, ay = self._cached_bar_loc
            scale = self._cached_scale
            char_x = int(ax + 710 * scale)
            char_y = int(ay - 350 * scale)
            return (char_x, char_y, scale)

        if screen is not None:
            matched, _, scale, ax, ay = self._find_bottom_bar_anchor(screen)
            if matched:
                char_x = int(ax + 710 * scale)
                char_y = int(ay - 350 * scale)
                return (char_x, char_y, scale)

        return (960, 545, 1.0)

    def get_hp_and_skill_state(self, screen: np.ndarray = None) -> dict:
        """
        Analyzes the bottom HUD bar to extract current HP percentage and Skill 2 readiness.
        Supports Fullscreen and Browser Window with multi-scale anchor tracking.
        - HP Orb: measures remaining red liquid level (0% - 100%).
        - Skill 2: measures HSV saturation (Colorful >= 20.0 = Ready, Greyscale < 20.0 = Cooldown).
        Returns dict with keys: found_ui, scale, hp_percent, skill_ready, skill_saturation, score, orb_center, skill_box.
        """
        if screen is None:
            screen = self.capture_screen()

        matched, score, scale, ax, ay = self._find_bottom_bar_anchor(screen)
        if not matched:
            return {
                "found_ui": False,
                "scale": 1.0,
                "hp_percent": 100.0,
                "skill_ready": False,
                "score": round(score, 3)
            }

        h, w = screen.shape[:2]

        # Scaled HUD coordinates relative to anchor
        orb_cx = ax + int(58 * scale)
        orb_cy = ay + int(55 * scale)
        r = int(49 * scale)

        s2_x1 = ax + int(203 * scale)
        s2_y1 = ay + int(35 * scale)
        s2_x2 = ax + int(265 * scale)
        s2_y2 = ay + int(95 * scale)

        # Calculate HP Percentage from Red Liquid Height & Pixel Count
        top_y = max(0, orb_cy - r)
        bot_y = min(h, orb_cy + r)
        left_x = max(0, orb_cx - r)
        right_x = min(w, orb_cx + r)

        level_pct = 100.0
        fill_ratio = 1.0

        if (bot_y - top_y >= 10) and (right_x - left_x >= 10):
            orb_crop = screen[top_y:bot_y, left_x:right_x]
            oh, ow = orb_crop.shape[:2]
            mask = np.zeros((oh, ow), dtype=np.uint8)
            cv2.circle(mask, (ow // 2, oh // 2), int(min(ow, oh) * 0.48), 255, -1)

            hsv_orb = cv2.cvtColor(orb_crop, cv2.COLOR_BGR2HSV)
            mask1 = cv2.inRange(hsv_orb, np.array([0, 75, 75]), np.array([12, 255, 255]))
            mask2 = cv2.inRange(hsv_orb, np.array([168, 75, 75]), np.array([180, 255, 255]))
            is_red = cv2.bitwise_or(mask1, mask2) & mask

            total_circle = np.sum(mask > 0)
            red_pixels = np.sum(is_red > 0)
            fill_ratio = (red_pixels / float(total_circle)) if total_circle > 0 else 0.0

            rows_with_red = [y for y in range(oh - 1, -1, -1) if np.sum(is_red[y, :]) >= 3]
            if rows_with_red:
                highest_red = min(rows_with_red)
                liquid_height = oh - highest_red
                level_pct = min(100.0, (liquid_height / float(oh)) * 100.0)
            else:
                level_pct = 0.0

        # Calculate Skill 2 Readiness (Color vs Greyscale)
        mean_sat = 0.0
        max_sat = 0.0
        skill_ready = False

        if (s2_y2 - s2_y1 >= 8) and (s2_x2 - s2_x1 >= 8):
            s2_crop = screen[s2_y1:s2_y2, s2_x1:s2_x2]
            sh, sw = s2_crop.shape[:2]
            inner_s2 = s2_crop[int(sh * 0.15):int(sh * 0.85), int(sw * 0.15):int(sw * 0.85)]
            hsv_s2 = cv2.cvtColor(inner_s2, cv2.COLOR_BGR2HSV)
            sat = hsv_s2[:, :, 1]
            mean_sat = float(np.mean(sat))
            max_sat = float(np.max(sat))
            skill_ready = bool(mean_sat >= 20.0 or max_sat >= 120.0)

        return {
            "found_ui": True,
            "scale": round(scale, 2),
            "score": round(score, 3),
            "hp_percent": round(level_pct, 1),
            "hp_area_percent": round(fill_ratio * 100.0, 1),
            "skill_ready": skill_ready,
            "skill_saturation": round(mean_sat, 1),
            "skill_max_sat": round(max_sat, 1),
            "orb_center": (orb_cx, orb_cy),
            "skill_box": (s2_x1, s2_y1, s2_x2, s2_y2)
        }

    def test_hp_and_skill_scan(self, hp_threshold: float = 40.0) -> dict:
        """Runs a live diagnostic test of HP orb and Skill 2 detection."""
        self.reload_templates()
        try:
            screen = self.capture_screen()
            info = self.get_hp_and_skill_state(screen)
            if not info.get("found_ui"):
                return {
                    "found": False,
                    "hp": 0.0,
                    "skill_ready": False,
                    "message": "❌ Game bottom HUD (HP / Skills) was not found. Make sure Dungeon Blitz is running and visible."
                }

            hp_val = info["hp_percent"]
            s_ready = info["skill_ready"]
            sat_val = info["skill_saturation"]

            status_heal = "Healing would trigger! ⚡" if (hp_val <= hp_threshold and s_ready) else (
                "Waiting (HP is sufficient)" if hp_val > hp_threshold else "Waiting on cooldown (greyscale)"
            )

            scale_val = info.get("scale", 1.0)
            scale_pct = int(scale_val * 100)
            mode_tag = "Browser Window" if scale_val < 0.98 else "Fullscreen"
            msg = (
                f"✅ GAME PANEL FOUND! [Scale: {scale_pct}% - {mode_tag}]\n"
                f"❤️ Detected Health (HP): {hp_val:.1f}%\n"
                f"✨ Skill 2: {'READY (Colored)' if s_ready else 'COOLDOWN (Greyscale)'} [Saturation: {sat_val}]\n"
                f"🎯 Configured Threshold: {hp_threshold:.0f}%\n"
                f"➡️ Heal Status: {status_heal}"
            )
            return {
                "found": True,
                "hp": hp_val,
                "skill_ready": s_ready,
                "message": msg,
                "info": info
            }
        except Exception as e:
            return {"found": False, "hp": 0.0, "skill_ready": False, "message": f"❌ Error during HP & Skill test: {e}"}

    def test_death_scan(self, threshold: float = 0.75) -> dict:
        """Runs a live diagnostic test for Death / Angel screen."""
        self.reload_templates()
        if not self.death_templates:
            return {
                "found": False,
                "score": 0.0,
                "message": "❌ Missing angel templates in 'targets' directory (revive_button.png)."
            }
        try:
            screen = self.capture_screen()
            found, score, loc, name = self.check_death(screen, threshold=threshold)
            score_pct = round(score * 100, 1)
            thresh_pct = round(threshold * 100, 1)
            if found:
                msg = f" ANGEL DETECTED! ({name}) with match {score_pct}% (threshold: {thresh_pct}%) at position {loc[0]}:{loc[1]}."
            else:
                msg = f" Angel not detected. Highest match in screen center is {score_pct}% (threshold is {thresh_pct}%)."
            return {"found": found, "score": score, "score_pct": score_pct, "message": msg, "location": loc}
        except Exception as e:
            return {"found": False, "score": 0.0, "message": f"❌ Screen grab error: {e}"}

    def test_disconnect_scan(self, threshold: float = 0.75) -> dict:
        """Runs a live diagnostic test for Lost Connection screen."""
        self.reload_templates()
        if not self.disconnect_templates:
            return {
                "found": False,
                "score": 0.0,
                "message": "❌ Missing disconnect templates in 'targets' directory (refresh_button.png)."
            }
        try:
            screen = self.capture_screen()
            found, score, loc, name = self.check_disconnect(screen, threshold=threshold)
            score_pct = round(score * 100, 1)
            thresh_pct = round(threshold * 100, 1)
            if found:
                msg = f" LOST CONNECTION DETECTED! ({name}) with match {score_pct}% (threshold: {thresh_pct}%) at position {loc[0]}:{loc[1]}."
            else:
                msg = f" Lost connection not detected. Highest match is {score_pct}% (threshold is {thresh_pct}%)."
            return {"found": found, "score": score, "score_pct": score_pct, "message": msg, "location": loc}
        except Exception as e:
            return {"found": False, "score": 0.0, "message": f"❌ Screen grab error: {e}"}

    def test_dungeon_complete_scan(self, threshold: float = 0.75) -> dict:
        """Runs a live diagnostic test for Dungeon Complete / Exit Dungeon screen."""
        self.reload_templates()
        if not self.dungeon_templates:
            return {
                "found": False,
                "score": 0.0,
                "message": "❌ Missing dungeon complete templates in 'targets' directory (exit_dungeon_button.png)."
            }
        try:
            screen = self.capture_screen()
            found, score, loc, name = self.check_dungeon_complete(screen, threshold=threshold)
            score_pct = round(score * 100, 1)
            thresh_pct = round(threshold * 100, 1)
            if found:
                msg = f" DUNGEON COMPLETE SCOREBOARD DETECTED! ({name}) with match {score_pct}% (threshold: {thresh_pct}%) at position {loc[0]}:{loc[1]}."
            else:
                msg = f" Dungeon scoreboard not detected. Highest match is {score_pct}% (threshold is {thresh_pct}%)."
            return {"found": found, "score": score, "score_pct": score_pct, "message": msg, "location": loc}
        except Exception as e:
            return {"found": False, "score": 0.0, "message": f"❌ Screen grab error: {e}"}

    def detect_enemy_hp_bars(self, screen: np.ndarray = None) -> list:
        """
        Detects enemy HP bars in the game playfield (both opaque hovered and semi-transparent unhovered).
        Supports Fullscreen and Browser Window with adaptive game rect bounding and scaling.
        Returns a list of dicts: [{'x', 'y', 'w', 'h', 'target_x', 'target_y'}, ...]
        sorted by distance to character center.
        """
        if screen is None:
            screen = self.capture_screen()

        sh, sw = screen.shape[:2]
        scale = self._cached_scale if self._cached_scale > 0 else 1.0

        if self._cached_game_rect is not None:
            gx1, gy1, gx2, gy2 = self._cached_game_rect
            x0 = max(0, gx1 + int(35 * scale))
            x1 = min(sw, gx2 - int(35 * scale))
            y0 = max(0, gy1 + int(50 * scale))
            y1 = min(sh, gy2 - int(110 * scale))
        else:
            x0 = max(0, int(sw * 0.14))
            x1 = min(sw, int(sw * 0.86))
            y0 = max(0, int(sh * 0.14))  # Safe against browser tabs/bookmarks
            y1 = min(sh, int(sh * 0.74))

        if (x1 - x0 < 50) or (y1 - y0 < 50):
            return []

        roi = screen[y0:y1, x0:x1]
        b = roi[:, :, 0].astype(np.int16)
        g = roi[:, :, 1].astype(np.int16)
        r = roi[:, :, 2].astype(np.int16)

        red_px = (
            (r >= 145) & (r <= 245) &
            (g >= 15) & (g <= 105) &
            (b >= 15) & (b <= 95) &
            ((r - g) >= 75) & ((r - b) >= 75)
        ).astype(np.uint8) * 255

        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(red_px)
        bars = []
        for i in range(1, num_labels):
            cx, cy, w, h, area = stats[i]
            # In browser (0.92x scale), bars can be 3px high; in fullscreen up to 9px
            if 3 <= h <= 9 and 4 <= w <= 55:
                fill_ratio = area / float(w * h)
                if fill_ratio >= 0.65 and (w / float(h)) >= 1.05:
                    if cy >= 2 and (cy + h + 2) < roi.shape[0]:
                        top_hl_r = float(np.mean(r[max(0, cy - 1):cy + 1, cx:cx + w]))
                        top_bdr = float(np.mean(r[max(0, cy - 3):cy - 1, cx:cx + w]))
                        bot_bdr = float(np.mean(r[cy + h:min(roi.shape[0], cy + h + 3), cx:cx + w]))
                        core_r = r[cy + 1:cy + min(h, 4), cx:cx + w]
                        row_means = np.mean(core_r, axis=1)
                        vert_diff = float(np.max(row_means) - np.min(row_means)) if len(row_means) > 1 else 0.0
                        if top_hl_r >= 140.0 and (top_hl_r - top_bdr) >= 18.0 and (top_hl_r - bot_bdr) >= 18.0 and vert_diff <= 15.0:
                            gx = int(x0 + cx + w // 2)
                            gy = int(y0 + cy + h // 2)
                            bars.append({
                                "x": gx,
                                "y": gy,
                                "w": int(w),
                                "h": int(h),
                                "target_x": gx,
                                "target_y": min(int(y1 + 15), gy + int(60 * scale))
                            })

        char_x, _, _ = self.get_character_center()
        bars.sort(key=lambda item: abs(item["x"] - char_x))
        return bars

    def get_skills_and_mana_state(self, screen: np.ndarray = None) -> dict:
        """
        Inspects the bottom HUD bar for Mana percentage (0-100%) and readiness (colorful vs greyscale)
        of Skills 1, 2, 3, 4, 5. Supports Fullscreen and Browser Window with scaled coordinates.
        """
        if screen is None:
            screen = self.capture_screen()

        base_info = self.get_hp_and_skill_state(screen)
        if not base_info.get("found_ui") or self._cached_bar_loc is None:
            return {
                "found_ui": False,
                "scale": 1.0,
                "hp_percent": 100.0,
                "mana_percent": 0.0,
                "skills_ready": {1: False, 2: False, 3: False, 4: False, 5: False},
                "skills_sat": {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}
            }

        ax, ay = self._cached_bar_loc
        scale = self._cached_scale
        sh, sw = screen.shape[:2]

        # Scaled Mana bar
        mx1 = max(0, ax + int(148 * scale))
        mx2 = min(sw, ax + int(342 * scale))
        my1 = max(0, ay + int(8 * scale))
        my2 = min(sh, ay + int(22 * scale))

        mana_pct = 0.0
        if (mx2 - mx1 >= 15) and (my2 - my1 >= 3):
            mana_roi = cv2.cvtColor(screen[my1:my2, mx1:mx2], cv2.COLOR_BGR2HSV)
            blue_mask = (
                (mana_roi[:, :, 0] >= 85) & (mana_roi[:, :, 0] <= 115) &
                (mana_roi[:, :, 1] >= 100) & (mana_roi[:, :, 2] >= 100)
            )
            col_has_blue = np.any(blue_mask, axis=0)
            mana_pct = round((float(np.sum(col_has_blue)) / float(len(col_has_blue))) * 100.0, 1)

        # Scaled Skills 1..5 slots
        skill_offsets = {
            1: (135, 38, 193, 92),
            2: (203, 38, 261, 92),
            3: (271, 38, 329, 92),
            4: (339, 38, 397, 92),
            5: (407, 38, 465, 92),
        }
        skills_ready = {}
        skills_sat = {}

        for s_num, (dx1, dy1, dx2, dy2) in skill_offsets.items():
            sx1 = max(0, ax + int(dx1 * scale))
            sy1 = max(0, ay + int(dy1 * scale))
            sx2 = min(sw, ax + int(dx2 * scale))
            sy2 = min(sh, ay + int(dy2 * scale))
            if (sx2 - sx1 >= 8) and (sy2 - sy1 >= 8):
                crop = screen[sy1:sy2, sx1:sx2]
                ch, cw = crop.shape[:2]
                inner = crop[int(ch * 0.12):int(ch * 0.88), int(cw * 0.12):int(cw * 0.88)]
                hsv_s = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
                sat = hsv_s[:, :, 1]
                m_sat = float(np.mean(sat))
                p95_sat = float(np.percentile(sat, 95))
                skills_sat[s_num] = round(m_sat, 1)
                skills_ready[s_num] = bool(m_sat >= 20.0 or p95_sat >= 100.0)
            else:
                skills_sat[s_num] = 0.0
                skills_ready[s_num] = False

        return {
            "found_ui": True,
            "scale": round(scale, 2),
            "hp_percent": base_info.get("hp_percent", 100.0),
            "mana_percent": mana_pct,
            "skills_ready": skills_ready,
            "skills_sat": skills_sat
        }

    def test_automat_scan(self) -> dict:
        """Runs a live diagnostic scan for Automat: Enemy HP bars, Mana, and Skills 1-5."""
        self.reload_templates()
        try:
            screen = self.capture_screen()
            bars = self.detect_enemy_hp_bars(screen)
            hud = self.get_skills_and_mana_state(screen)
            sr = hud.get("skills_ready", {})
            s_str = " | ".join([f"S{i}: {'✅' if sr.get(i) else '⚪'}" for i in (1, 2, 3, 4, 5)])
            bars_str = ", ".join([f"({b['x']}, {b['y']})" for b in bars[:4]]) if bars else "No enemies on screen"
            msg = (
                f"👾 Detected Enemy HP bars: {len(bars)} [{bars_str}]\n"
                f"❤️ HP: {hud.get('hp_percent', 0):.1f}%  |  💧 Mana: {hud.get('mana_percent', 0):.1f}%\n"
                f"✨ Skills: {s_str}"
            )
            return {
                "found_ui": hud.get("found_ui", False),
                "mob_count": len(bars),
                "bars": bars,
                "hud": hud,
                "message": msg
            }
        except Exception as e:
            return {"found_ui": False, "mob_count": 0, "bars": [], "message": f"❌ Error testing Auto-Mob: {e}"}
