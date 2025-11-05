# space dodge — rehab build (with sfx + seamless looping music)
# all comments are intentionally in lower case to match your request

import pygame
import time
import random
import math
from collections import deque
import os
import csv
import uuid
import json
from datetime import datetime

# --- init pygame and mixer ---
pygame.init()
pygame.font.init()
pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

# --- sfx / music setup ---
# all .wav files live here (hit.wav, shield.wav, slow.wav, space_song.wav)
FX_DIR = "fx"
MUSIC_CH = None  # will hold the channel returned by the looping music sound


def load_sound(name, volume=1.0):
    """load a .wav from fx/ with a set volume; returns pygame.mixer.Sound or None."""
    path = os.path.join(FX_DIR, name)
    try:
        s = pygame.mixer.Sound(path)
        s.set_volume(volume)
        return s
    except pygame.error as e:
        print(f"[warn] could not load sound {path}: {e}")
        return None


# sfx
HIT_SFX = load_sound("hit.wav",    volume=0.9)
SHIELD_SFX = load_sound("shield.wav", volume=0.9)
SLOW_SFX = load_sound("slow.wav",   volume=0.9)

# background music as a sound object (for seamless in-memory looping)
SPACE_SONG = load_sound("space_song.wav", volume=0.6)

# --- data logging setup ---
SUBJECT_ID = "anon001"          # set a pseudonymous id (no pii)
PROTOCOL_VERSION = "v0.3-rehab"
BLOCK_SECONDS = 60               # metrics aggregated & logged each block

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


def iso_now():
    """utc iso timestamp with ms precision and 'z' suffix."""
    return datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


class RehabLogger:
    """simple csv logger writing three streams: sessions, blocks, events."""

    def __init__(self, base_dir=LOG_DIR):
        self.base_dir = base_dir
        self.sessions_path = os.path.join(base_dir, "sessions.csv")
        self.blocks_path = os.path.join(base_dir, "blocks.csv")
        self.events_path = os.path.join(base_dir, "events.csv")
        self._ensure_headers()

    def _ensure_headers(self):
        if not os.path.exists(self.sessions_path):
            with open(self.sessions_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    "ts_start", "ts_end", "session_id", "subject_id", "protocol_version",
                    "notes", "config_json", "duration_sec", "final_difficulty", "lives_remaining",
                    "shields_collected", "near_misses", "meteors_spawned", "meteors_avoided"
                ])
        if not os.path.exists(self.blocks_path):
            with open(self.blocks_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    "ts_start", "ts_end", "session_id", "block_idx", "duration_sec",
                    "difficulty_avg", "speed_scale_avg", "meteors_spawned", "meteors_avoided",
                    "hits", "near_misses", "movement_px", "success_rate"
                ])
        if not os.path.exists(self.events_path):
            with open(self.events_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["ts", "session_id", "type", "detail_json"])

    def write_session_start(self, session_id, subject_id, protocol_version, notes, config):
        # write a start row; an end row will contain final summary
        with open(self.sessions_path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                iso_now(), "", session_id, subject_id, protocol_version, notes, json.dumps(config),
                "", "", "", "", "", "", ""
            ])

    def write_session_end_summary(self, session_id, duration_sec, final_difficulty,
                                  lives_remaining, shields_collected, near_misses,
                                  meteors_spawned, meteors_avoided):
        # write an end row (separate, to avoid updating in place)
        with open(self.sessions_path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "", iso_now(), session_id, SUBJECT_ID, PROTOCOL_VERSION, "SESSION_END", "{}",
                f"{duration_sec:.2f}", f"{final_difficulty:.2f}", lives_remaining,
                shields_collected, near_misses, meteors_spawned, meteors_avoided
            ])

    def write_block(self, session_id, block_idx, ts_start, ts_end, dur, diff_avg, speed_avg,
                    spawned, avoided, hits, near_misses, movement_px):
        # compute success rate as avoided/spawned when spawned > 0, else blank
        sr = (avoided / spawned) if spawned > 0 else ""
        with open(self.blocks_path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                ts_start, ts_end, session_id, block_idx,
                f"{dur:.2f}", f"{diff_avg:.3f}", f"{speed_avg:.3f}",
                spawned, avoided, hits, near_misses, int(movement_px),
                f"{sr:.3f}" if sr != "" else ""
            ])

    def write_event(self, session_id, etype, detail_dict):
        with open(self.events_path, "a", newline="") as f:
            w = csv.writer(f)
            w.writerow([iso_now(), session_id, etype, json.dumps(detail_dict)])


# --- window / assets ---
WIDTH, HEIGHT = 1000, 600
WINDOW = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Space Dodge — Rehab Build")

PIXEL_SCALE = 3
LOW_W, LOW_H = WIDTH // PIXEL_SCALE, HEIGHT // PIXEL_SCALE
SCANLINE_ALPHA = 36

FRAME = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

# background art (ensure files exist in your working dir)
BG = pygame.transform.scale(pygame.image.load(
    "space_bg.png").convert(), (WIDTH, HEIGHT))
MOON = pygame.image.load("moon1.png").convert_alpha()
MOON_RECT = MOON.get_rect(topright=(WIDTH - 12, 12))

# scanline overlay
SCANLINES = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
if SCANLINE_ALPHA > 0:
    for y in range(0, HEIGHT, 2):
        pygame.draw.line(SCANLINES, (0, 0, 0, SCANLINE_ALPHA),
                         (0, y), (WIDTH, y))

# font (press start 2p if present; else fallback)


def load_pixel_font(size=18):
    if os.path.exists("PressStart2P.ttf"):
        return pygame.font.Font("PressStart2P.ttf", size)
    return pygame.font.SysFont("couriernew", size, bold=True)


FONT = load_pixel_font(18)


def text_with_shadow(surf, msg, x, y, color=(255, 255, 255)):
    """draw tiny black shadow then white text for readability."""
    shadow = FONT.render(msg, True, (0, 0, 0))
    surf.blit(shadow, (x + 1, y + 1))
    surf.blit(FONT.render(msg, True, color), (x, y))


def pixel_present(frame_surface):
    """downsample then upsample to simulate chunky pixels; draw scanlines."""
    low = pygame.transform.scale(frame_surface, (LOW_W, LOW_H))
    up = pygame.transform.scale(low, (WIDTH, HEIGHT))
    WINDOW.blit(up, (0, 0))
    if SCANLINE_ALPHA > 0:
        WINDOW.blit(SCANLINES, (0, 0))


def hud_panel(rect, alpha=190):
    """semi-opaque hud background panel."""
    panel = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    panel.fill((0, 0, 0, alpha))
    WINDOW.blit(panel, rect.topleft)


def draw_hud_overlay(score_time, difficulty, lives, fall_speed_scale, shield_active,
                     slowmo_ms, shields_collected, near_misses, spawned, avoided, paused=False):
    """draw top-left hud with simple rehab metrics."""
    panel_rect = pygame.Rect(8, 8, 520, 160 if not paused else 190)
    hud_panel(panel_rect, alpha=200)
    x, y = panel_rect.left + 10, panel_rect.top + 10

    # row 1
    text_with_shadow(WINDOW, f"TIME {int(score_time)}s", x, y)
    text_with_shadow(WINDOW, f"DIFF {difficulty:.2f}", x + 180, y)
    text_with_shadow(WINDOW, f"LIVES {lives}", x + 320, y)

    # row 2
    # success rate proxy in hud
    sr = (avoided / spawned) if spawned > 0 else 0.0
    text_with_shadow(WINDOW, f"SPD  {fall_speed_scale:.2f}", x, y + 28)
    text_with_shadow(WINDOW, f"SR   {sr:.2f}", x + 180, y + 28)
    text_with_shadow(WINDOW, f"NMIS {near_misses}", x + 320, y + 28)

    # row 3
    text_with_shadow(
        WINDOW, f"SHIELDS COLLECTED {shields_collected}", x, y + 56)

    # row 4 (status flags)
    status = []
    if shield_active:
        status.append("SHIELD READY")
    if slowmo_ms > 0:
        status.append(f"SLOW {int(slowmo_ms/1000)}s")
    if status:
        text_with_shadow(WINDOW, " / ".join(status), x, y + 84)

    # row 5 (help + paused)
    text_with_shadow(WINDOW, "P=PAUSE  R=RESTART  ESC=QUIT", x, y + 112)
    if paused:
        text_with_shadow(WINDOW, "PAUSED", x + 360, y + 112)


def draw_game_over_overlay(score_time, difficulty, shields_collected, near_misses, spawned, avoided):
    """center game over card with a summary line."""
    panel = pygame.Surface((WIDTH, 160), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 210))
    WINDOW.blit(panel, (0, HEIGHT // 2 - 80))
    title = "GAME OVER — Press R to restart, ESC to quit"
    stats = (
        f"TIME {int(score_time)}s  DIFF {difficulty:.2f}  SHIELDS {shields_collected}  SR {(avoided/spawned):.2f}"
        if spawned > 0 else
        f"TIME {int(score_time)}s  DIFF {difficulty:.2f}  SHIELDS {shields_collected}"
    )
    text_with_shadow(WINDOW, title, WIDTH // 2 -
                     FONT.size(title)[0] // 2, HEIGHT // 2 - 36)
    text_with_shadow(WINDOW, stats, WIDTH // 2 -
                     FONT.size(stats)[0] // 2, HEIGHT // 2 + 4)


# --- sprites / gameplay params ---
PLAYER_WIDTH, PLAYER_HEIGHT = 150, 150
PLAYER_VEL = 5
ANIMATION_MS_IDLE, ANIMATION_MS_MOVE = 140, 90

PLAYER_FRAMES = [
    pygame.transform.scale(pygame.image.load(
        "Rocket1.png").convert_alpha(), (PLAYER_WIDTH, PLAYER_HEIGHT)),
    pygame.transform.scale(pygame.image.load(
        "Rocket2.png").convert_alpha(), (PLAYER_WIDTH, PLAYER_HEIGHT)),
]
PLAYER_MASKS = [pygame.mask.from_surface(img) for img in PLAYER_FRAMES]

STAR_WIDTH, STAR_HEIGHT = 100, 100
STAR_VEL_BASE = 3
METEOR_ANIM_MS = 120
MAX_TILT_DEG_BASE = 35

METEOR_FRAMES = [
    pygame.transform.scale(pygame.image.load(
        "Meteor1.png").convert_alpha(), (STAR_WIDTH, STAR_HEIGHT)),
    pygame.transform.scale(pygame.image.load(
        "Meteor2.png").convert_alpha(), (STAR_WIDTH, STAR_HEIGHT)),
]

# dda (difficulty adjustment)
DIFF_MIN, DIFF_MAX, DIFF_START = 0.6, 3.0, 0.9
DIFF_UP_PER_SEC, DIFF_UP_MOVING_BONUS = 0.02, 0.015
DIFF_MULT_DROP_ON_HIT, DIFF_ABS_DROP_ON_HIT = 0.75, 0.10
DIFF_COOLDOWN_AFTER_HIT_SEC = 3.0

# movement activity window (to grant bonus difficulty growth when actively moving)
MOVEMENT_ACTIVE_THRESHOLD, MOVEMENT_WINDOW_SEC = 160, 5.0

# lives / invulnerability
LIVES_START, INVULN_MS_AFTER_HIT = 3, 1000

# falling speed scale (slows down after a hit, recovers over time)
FALL_SPEED_SCALE_START, FALL_SPEED_SCALE_MIN = 1.0, 0.5
FALL_SPEED_SCALE_HIT_FACTOR, FALL_SPEED_RECOVERY_PER_SEC = 0.8, 0.05

# spawn pacing penalty (after hits), then decays
SPAWN_INTERVAL_PENALTY_MAX_MS, SPAWN_INTERVAL_PENALTY_DECAY_PER_SEC = 800, 200.0

# power-ups
POWERUP_RADIUS = 16
SHIELD_COLOR, SLOWMO_COLOR = (80, 220, 255), (255, 210, 80)
SLOWMO_DURATION_MS = 3000
POWERUP_SPAWN_INTERVAL_MIN, POWERUP_SPAWN_INTERVAL_MAX = 6000, 11000
POWERUP_VY_BASE, POWERUP_DRIFT_MAX = 2.2, 0.5
SHIELD_DROP_CHANCE, SHIELD_RESPAWN_COOLDOWN_MS = 0.20, 8000

# camera shake
SHAKE_MS, SHAKE_PIX = 350, 6

# --- small helpers ---


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def lerp(a, b, t):
    return a + (b - a) * t


def circle_hit_rect(circle_center, r, rect):
    """circle-rect hit test used for powerup pickup."""
    cx, cy = circle_center
    rx = clamp(cx, rect.left, rect.right)
    ry = clamp(cy, rect.top, rect.bottom)
    dx, dy = cx - rx, cy - ry
    return (dx * dx + dy * dy) <= r * r


def spawn_meteor(difficulty):
    """create a meteor dict with drift/tilt based on difficulty."""
    drift_mag = lerp(1.0, 3.0, (difficulty - DIFF_MIN) / (DIFF_MAX - DIFF_MIN))
    vx = random.uniform(-drift_mag, drift_mag)
    ang = random.uniform(-12, 12)
    x = random.randint(0, WIDTH - STAR_WIDTH)
    y = -STAR_HEIGHT
    rect = pygame.Rect(x, y, STAR_WIDTH, STAR_HEIGHT)
    base_frame = 0
    base_surf = METEOR_FRAMES[base_frame]
    rot_surf = pygame.transform.rotate(base_surf, ang)
    rot_rect = rot_surf.get_rect(center=rect.center)
    rot_mask = pygame.mask.from_surface(rot_surf)
    return {
        "fx": float(rect.centerx), "fy": float(rect.centery), "vx": vx,
        "frame": base_frame, "anim_timer": 0, "angle": ang,
        "surf": rot_surf, "rect": rot_rect, "mask": rot_mask,
        "passed_player": False, "near_checked": False
    }


def spawn_powerup(shield_allowed=True):
    """spawn a shield (if allowed by cooldown) or slowmo powerup."""
    kind = "shield" if (shield_allowed and random.random()
                        < SHIELD_DROP_CHANCE) else "slowmo"
    x = random.randint(POWERUP_RADIUS + 20, WIDTH - POWERUP_RADIUS - 20)
    y = -POWERUP_RADIUS - 30
    vx = random.uniform(-POWERUP_DRIFT_MAX, POWERUP_DRIFT_MAX)
    return {"kind": kind, "pos": [float(x), float(y)], "r": POWERUP_RADIUS, "vx": vx, "alive": True}


def draw_powerup(surface, pu, cam_x=0, cam_y=0):
    """render a simple colored circle for powerups."""
    color = SHIELD_COLOR if pu["kind"] == "shield" else SLOWMO_COLOR
    p = (int(pu["pos"][0]) + cam_x, int(pu["pos"][1]) + cam_y)
    pygame.draw.circle(surface, color, p, pu["r"])
    pygame.draw.circle(surface, (255, 255, 255), p, pu["r"], 2)


def pixel_scene_and_hud(frame, player, player_frame_idx, meteors, score_time, difficulty, lives,
                        fall_speed_scale, shield_active, slowmo_ms, shields_collected,
                        near_misses, spawned, avoided, powerups, shake_ms, paused, game_over,
                        show_game_over_panel):
    """compose the frame, present it pixelated, draw hud, and optional overlays."""
    frame.fill((0, 0, 0, 0))
    cam_x = random.randint(-SHAKE_PIX, SHAKE_PIX) if shake_ms > 0 else 0
    cam_y = random.randint(-SHAKE_PIX, SHAKE_PIX) if shake_ms > 0 else 0
    frame.blit(BG, (cam_x, cam_y))
    frame.blit(MOON, (MOON_RECT.x + cam_x, MOON_RECT.y + cam_y))
    frame.blit(PLAYER_FRAMES[player_frame_idx],
               (player.x + cam_x, player.y + cam_y))
    for m in meteors:
        frame.blit(m["surf"], (m["rect"].x + cam_x, m["rect"].y + cam_y))
    for pu in powerups:
        draw_powerup(frame, pu, cam_x, cam_y)
    if slowmo_ms > 0:
        tint = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        tint.fill((120, 180, 255, 60))
        frame.blit(tint, (0, 0))
    pixel_present(frame)
    draw_hud_overlay(score_time, difficulty, lives, fall_speed_scale, shield_active, slowmo_ms,
                     shields_collected, near_misses, spawned, avoided, paused=paused)
    if show_game_over_panel:
        draw_game_over_overlay(score_time, difficulty,
                               shields_collected, near_misses, spawned, avoided)
    pygame.display.update()

# --- main/game loops ---


def main():
    """start background music loop, then run game sessions until exit."""
    global MUSIC_CH
    if SPACE_SONG:
        # loops=-1 means infinite loop; using sound.play helps reduce seams versus mixer.music
        MUSIC_CH = SPACE_SONG.play(loops=-1)

    while True:
        if not run_game():
            break

    # on final exit
    if MUSIC_CH:
        MUSIC_CH.stop()


def run_game():
    """one full playable session; returns false to exit app, true to restart."""
    # session init & logger
    session_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S") + \
        "-" + uuid.uuid4().hex[:6]
    logger = RehabLogger()
    config = {
        "pixel_scale": PIXEL_SCALE, "scanline_alpha": SCANLINE_ALPHA,
        "block_seconds": BLOCK_SECONDS, "protocol": PROTOCOL_VERSION,
        "dda": {"diff_min": DIFF_MIN, "diff_max": DIFF_MAX, "diff_start": DIFF_START}
    }
    logger.write_session_start(
        session_id, SUBJECT_ID, PROTOCOL_VERSION, notes="", config=config)

    # game state
    paused = False
    player_frame_idx = 0
    player_anim_timer = 0
    player = pygame.Rect(200, HEIGHT - PLAYER_HEIGHT -
                         10, PLAYER_WIDTH, PLAYER_HEIGHT)

    clock = pygame.time.Clock()
    score_time = 0.0
    difficulty = DIFF_START
    lives = LIVES_START
    invuln_ms_remaining = 0
    fall_speed_scale = FALL_SPEED_SCALE_START
    spawn_interval_penalty_ms = 0.0
    diff_cooldown_timer = 0.0

    star_add_interval_ms = 1600
    star_spawn_accum = 0
    meteors = []

    powerups = []
    powerup_timer_ms = 0
    next_powerup_in_ms = random.randint(
        POWERUP_SPAWN_INTERVAL_MIN, POWERUP_SPAWN_INTERVAL_MAX)
    shield_active = False
    slowmo_ms = 0
    shields_collected = 0
    shield_cooldown_ms = 0

    move_samples = deque()
    shake_ms = 0
    game_over = False

    # metrics (overall)
    meteors_spawned_total = 0
    meteors_avoided_total = 0
    near_misses_total = 0

    # block metrics
    block_idx = 0
    block_t0 = time.time()
    block_diff_acc = 0.0
    block_speed_acc = 0.0
    block_dur_acc = 0.0
    block_spawned = 0
    block_avoided = 0
    block_hits = 0
    block_near_misses = 0
    block_movement_px = 0

    while True:
        dt_ms = clock.tick(60)
        dt_s = dt_ms / 1000.0

        # events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if MUSIC_CH:
                    MUSIC_CH.stop()
                logger.write_session_end_summary(
                    session_id, score_time, difficulty, lives,
                    shields_collected, near_misses_total,
                    meteors_spawned_total, meteors_avoided_total
                )
                pygame.quit()
                return False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if MUSIC_CH:
                        MUSIC_CH.stop()
                    logger.write_session_end_summary(
                        session_id, score_time, difficulty, lives,
                        shields_collected, near_misses_total,
                        meteors_spawned_total, meteors_avoided_total
                    )
                    pygame.quit()
                    return False

                if event.key == pygame.K_p and not game_over:
                    paused = not paused

                if event.key == pygame.K_r and game_over:
                    logger.write_session_end_summary(
                        session_id, score_time, difficulty, lives,
                        shields_collected, near_misses_total,
                        meteors_spawned_total, meteors_avoided_total
                    )
                    return True  # restart

        if game_over:
            # freeze scene; show overlay
            pixel_scene_and_hud(
                FRAME, player, player_frame_idx, meteors, score_time, difficulty, lives,
                fall_speed_scale, shield_active, slowmo_ms, shields_collected,
                near_misses_total, meteors_spawned_total, meteors_avoided_total,
                powerups, 0, paused=False, game_over=True, show_game_over_panel=True
            )
            continue

        if paused:
            pixel_scene_and_hud(
                FRAME, player, player_frame_idx, meteors, score_time, difficulty, lives,
                fall_speed_scale, shield_active, slowmo_ms, shields_collected,
                near_misses_total, meteors_spawned_total, meteors_avoided_total,
                powerups, 0, paused=True, game_over=False, show_game_over_panel=False
            )
            continue

        # timers & decay
        star_spawn_accum += dt_ms
        score_time += dt_s
        if invuln_ms_remaining > 0:
            invuln_ms_remaining -= dt_ms
        if diff_cooldown_timer > 0:
            diff_cooldown_timer -= dt_s
        if slowmo_ms > 0:
            slowmo_ms -= dt_ms
        if shake_ms > 0:
            shake_ms -= dt_ms
        if shield_cooldown_ms > 0:
            shield_cooldown_ms -= dt_ms

        if spawn_interval_penalty_ms > 0:
            spawn_interval_penalty_ms = max(
                0.0, spawn_interval_penalty_ms - SPAWN_INTERVAL_PENALTY_DECAY_PER_SEC * dt_s)
        if fall_speed_scale < 1.0:
            fall_speed_scale = min(
                1.0, fall_speed_scale + FALL_SPEED_RECOVERY_PER_SEC * dt_s)

        keys = pygame.key.get_pressed()

        # dda parameters derived from current difficulty
        base_spawn_target_ms = int(
            lerp(2000, 400, (difficulty - DIFF_MIN) / (DIFF_MAX - DIFF_MIN)))
        spawn_interval_target_ms = int(
            base_spawn_target_ms + spawn_interval_penalty_ms)
        base_vy = STAR_VEL_BASE * \
            lerp(0.85, 1.7, (difficulty - DIFF_MIN) / (DIFF_MAX - DIFF_MIN))
        vy = base_vy * fall_speed_scale
        if slowmo_ms > 0:
            vy *= 0.6
        max_tilt_deg = MAX_TILT_DEG_BASE + \
            lerp(0, 10, (difficulty - DIFF_MIN) / (DIFF_MAX - DIFF_MIN))

        # smooth adjust toward target spawn interval
        star_add_interval_ms = int(
            star_add_interval_ms + (spawn_interval_target_ms - star_add_interval_ms) * 0.15)

        # meteor spawns (waves scale with difficulty)
        if star_spawn_accum >= star_add_interval_ms:
            wave = 2 if difficulty < 1.2 else 3 if difficulty < 2.0 else 4
            for _ in range(wave):
                meteors.append(spawn_meteor(difficulty))
                meteors_spawned_total += 1
                block_spawned += 1
            star_spawn_accum = 0

        # spawn powerups
        powerup_timer_ms += dt_ms
        if powerup_timer_ms >= next_powerup_in_ms:
            pu = spawn_powerup(shield_allowed=(shield_cooldown_ms <= 0))
            powerups.append(pu)
            logger.write_event(session_id, "powerup_spawn", {
                               "kind": pu["kind"], "x": int(pu["pos"][0])})
            powerup_timer_ms = 0
            next_powerup_in_ms = random.randint(
                POWERUP_SPAWN_INTERVAL_MIN, POWERUP_SPAWN_INTERVAL_MAX)
            if pu["kind"] == "shield":
                shield_cooldown_ms = SHIELD_RESPAWN_COOLDOWN_MS

        # player animation & movement
        anim_target = ANIMATION_MS_MOVE if (
            keys[pygame.K_LEFT] or keys[pygame.K_RIGHT]) else ANIMATION_MS_IDLE
        player_anim_timer += dt_ms
        if player_anim_timer >= anim_target:
            player_frame_idx = (player_frame_idx + 1) % len(PLAYER_FRAMES)
            player_anim_timer = 0

        prev_x = player.x
        if keys[pygame.K_LEFT] and player.x - PLAYER_VEL >= 0:
            player.x -= PLAYER_VEL
        if keys[pygame.K_RIGHT] and player.x + PLAYER_VEL + player.width <= WIDTH:
            player.x += PLAYER_VEL
        dx = abs(player.x - prev_x)

        # keep only last movement_window_sec seconds of dx samples
        now_t = time.time()
        move_samples.append((now_t, dx))
        while move_samples and now_t - move_samples[0][0] > MOVEMENT_WINDOW_SEC:
            move_samples.popleft()  # fixed: use popleft() on deque

        # compute total movement over the recent window to mark active movement
        total_dx_window = sum(s[1] for s in move_samples)
        moving_actively = total_dx_window >= MOVEMENT_ACTIVE_THRESHOLD

        # update meteors & collisions
        rocket_mask = PLAYER_MASKS[player_frame_idx]
        hit_this_frame = False

        for m in meteors[:]:
            # simple animation toggle
            m["anim_timer"] += dt_ms
            if m["anim_timer"] >= METEOR_ANIM_MS:
                m["frame"] = (m["frame"] + 1) % len(METEOR_FRAMES)
                m["anim_timer"] = 0

            # integrate motion
            m["fx"] += m["vx"]
            m["fy"] += vy

            # aim tilt into movement direction
            desired_angle_rad = math.atan2(-m["vx"], vy if vy != 0 else 0.0001)
            desired_angle_deg = math.degrees(desired_angle_rad)
            target_ang = clamp(desired_angle_deg, -max_tilt_deg, max_tilt_deg)
            m["angle"] += (target_ang - m["angle"]) * 0.2

            # clamp drift to screen; bounce a bit to avoid leaving area
            if m["fx"] < 0:
                m["fx"] = 0
                m["vx"] = abs(m["vx"]) * 0.8
            elif m["fx"] > WIDTH:
                m["fx"] = WIDTH
                m["vx"] = -abs(m["vx"]) * 0.8

            # regenerate rotated sprite/mask at new angle
            base_surf = METEOR_FRAMES[m["frame"]]
            rot_surf = pygame.transform.rotate(base_surf, m["angle"])
            rot_rect = rot_surf.get_rect(center=(int(m["fx"]), int(m["fy"])))
            rot_mask = pygame.mask.from_surface(rot_surf)
            m["surf"], m["rect"], m["mask"] = rot_surf, rot_rect, rot_mask

            # near-miss detection when crossing player's y
            if not m["near_checked"] and m["rect"].centery >= player.centery:
                m["near_checked"] = True
                if abs(m["rect"].centerx - player.centerx) <= 30:
                    near_misses_total += 1
                    block_near_misses += 1
                    logger.write_event(session_id, "near_miss", {
                                       "dx": abs(m["rect"].centerx - player.centerx)})

            # off-screen => avoided
            if m["rect"].top > HEIGHT + 50:
                meteors.remove(m)
                meteors_avoided_total += 1
                block_avoided += 1
                continue

            # collisions (respect shield & invuln)
            if invuln_ms_remaining <= 0:
                offset = (m["rect"].x - player.x, m["rect"].y - player.y)
                if rocket_mask.overlap(m["mask"], offset):
                    if shield_active:
                        shield_active = False
                        meteors.remove(m)
                        shake_ms = max(shake_ms, SHAKE_MS // 2)
                        logger.write_event(session_id, "shield_used", {
                                           "difficulty": round(difficulty, 2)})
                        # play optional sfx for shield absorb (use shield sfx on pickup per spec)
                    else:
                        meteors.remove(m)
                        hit_this_frame = True
                        if HIT_SFX:
                            HIT_SFX.play()
                    break  # resolve just one collision per frame
            # note: while invulnerable, we blink visually (handled at draw time)

        # powerups falling + pickup
        pu_vy = POWERUP_VY_BASE * fall_speed_scale * \
            (0.6 if slowmo_ms > 0 else 1.0)
        for pu in powerups[:]:
            pu["pos"][1] += pu_vy
            pu["pos"][0] += pu["vx"]
            if pu["pos"][0] < POWERUP_RADIUS:
                pu["pos"][0] = POWERUP_RADIUS
                pu["vx"] = abs(pu["vx"])
            elif pu["pos"][0] > WIDTH - POWERUP_RADIUS:
                pu["pos"][0] = WIDTH - \
                    POWEROP_RADIUS if False else WIDTH - POWERUP_RADIUS
                pu["vx"] = -abs(pu["vx"])

            if pu["alive"] and circle_hit_rect((pu["pos"][0], pu["pos"][1]), pu["r"], player):
                pu["alive"] = False
                if pu["kind"] == "shield":
                    shield_active = True
                    shields_collected += 1
                    if SHIELD_SFX:
                        SHIELD_SFX.play()
                else:
                    slowmo_ms = SLOWMO_DURATION_MS
                    if SLOW_SFX:
                        SLOW_SFX.play()
                logger.write_event(session_id, "powerup_pickup", {
                                   "kind": pu["kind"]})

            if pu["pos"][1] - pu["r"] > HEIGHT + 20 or not pu["alive"]:
                powerups.remove(pu)

        # resolve a hit if it occurred this frame
        if hit_this_frame:
            lives = max(0, lives - 1)
            block_hits += 1
            logger.write_event(session_id, "hit", {
                               "lives_after": lives, "difficulty": round(difficulty, 2)})

            # apply difficulty drop, speed slowdown, spawn penalty, cooldown, invuln
            difficulty = clamp(difficulty * DIFF_MULT_DROP_ON_HIT -
                               DIFF_ABS_DROP_ON_HIT, DIFF_MIN, DIFF_MAX)
            fall_speed_scale = max(
                FALL_SPEED_SCALE_MIN, fall_speed_scale * FALL_SPEED_SCALE_HIT_FACTOR)
            spawn_interval_penalty_ms = min(
                SPAWN_INTERVAL_PENALTY_MAX_MS, spawn_interval_penalty_ms +
                SPAWN_INTERVAL_PENALTY_MAX_MS * 0.6
            )
            diff_cooldown_timer = DIFF_COOLDOWN_AFTER_HIT_SEC
            invuln_ms_remaining = INVULN_MS_AFTER_HIT

            # clear active meteors and reset spawn accumulator
            meteors.clear()
            star_spawn_accum = 0

            # add camera shake
            shake_ms = max(shake_ms, SHAKE_MS)

            # if no lives left, end the run and flush the final (possibly partial) block
            if lives <= 0:
                game_over = True
                bt1 = time.time()
                dur = bt1 - block_t0
                if dur > 0.25:
                    logger.write_block(
                        session_id, block_idx,
                        datetime.utcfromtimestamp(block_t0).isoformat() + "Z",
                        datetime.utcfromtimestamp(bt1).isoformat() + "Z",
                        dur, block_diff_acc /
                        max(dur, 1e-6), block_speed_acc / max(dur, 1e-6),
                        block_spawned, block_avoided, block_hits, block_near_misses, block_movement_px
                    )

        # raise difficulty steadily (plus bonus if moving) unless cooling down
        if diff_cooldown_timer <= 0 and not game_over:
            difficulty += DIFF_UP_PER_SEC * dt_s
            if moving_actively:
                difficulty += DIFF_UP_MOVING_BONUS * dt_s
            difficulty = clamp(difficulty, DIFF_MIN, DIFF_MAX)

        # accumulate block metrics
        block_dur_acc += dt_s
        block_diff_acc += difficulty * dt_s
        block_speed_acc += fall_speed_scale * dt_s
        block_movement_px += dx

        # end & log block
        if block_dur_acc >= BLOCK_SECONDS:
            bt1 = time.time()
            logger.write_block(
                session_id, block_idx,
                datetime.utcfromtimestamp(block_t0).isoformat() + "Z",
                datetime.utcfromtimestamp(bt1).isoformat() + "Z",
                block_dur_acc,
                block_diff_acc / max(block_dur_acc, 1e-6),
                block_speed_acc / max(block_dur_acc, 1e-6),
                block_spawned, block_avoided, block_hits, block_near_misses, block_movement_px
            )
            # reset accumulators for next block
            block_idx += 1
            block_t0 = bt1
            block_dur_acc = 0.0
            block_diff_acc = 0.0
            block_speed_acc = 0.0
            block_spawned = 0
            block_avoided = 0
            block_hits = 0
            block_near_misses = 0
            block_movement_px = 0

        # draw (with player blinking while invulnerable)
        if invuln_ms_remaining > 0 and ((invuln_ms_remaining // 100) % 2 == 0):
            tmp = PLAYER_FRAMES[player_frame_idx]
            PLAYER_FRAMES[player_frame_idx] = pygame.Surface(
                (PLAYER_WIDTH, PLAYER_HEIGHT), pygame.SRCALPHA)
            pixel_scene_and_hud(
                FRAME, player, player_frame_idx, meteors, score_time, difficulty, lives,
                fall_speed_scale, shield_active, slowmo_ms, shields_collected,
                near_misses_total, meteors_spawned_total, meteors_avoided_total,
                powerups, shake_ms, paused=False, game_over=game_over, show_game_over_panel=False
            )
            PLAYER_FRAMES[player_frame_idx] = tmp
        else:
            pixel_scene_and_hud(
                FRAME, player, player_frame_idx, meteors, score_time, difficulty, lives,
                fall_speed_scale, shield_active, slowmo_ms, shields_collected,
                near_misses_total, meteors_spawned_total, meteors_avoided_total,
                powerups, shake_ms, paused=False, game_over=game_over, show_game_over_panel=False
            )

        # if game over, show one more pass with the game-over overlay
        if game_over:
            pixel_scene_and_hud(
                FRAME, player, player_frame_idx, meteors, score_time, difficulty, lives,
                fall_speed_scale, shield_active, slowmo_ms, shields_collected,
                near_misses_total, meteors_spawned_total, meteors_avoided_total,
                powerups, 0, paused=False, game_over=True, show_game_over_panel=True
            )

    # unreachable
    return False


if __name__ == "__main__":
    main()
