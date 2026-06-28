from __future__ import annotations


ScreenBounds = tuple[int, int, int, int]
ScreenRect = tuple[int, int, int, int]


def clamp_hud_position(
    x: int,
    y: int,
    width: int,
    height: int,
    bounds: ScreenBounds,
    *,
    margin: int = 8,
) -> tuple[int, int]:
    left, top, right, bottom = bounds
    min_x = left + margin
    min_y = top + margin
    max_x = max(min_x, right - width - margin)
    max_y = max(min_y, bottom - height - margin)
    return max(min_x, min(int(x), max_x)), max(min_y, min(int(y), max_y))


def fits_hud_position(
    x: int,
    y: int,
    width: int,
    height: int,
    bounds: ScreenBounds,
    *,
    margin: int = 8,
) -> bool:
    left, top, right, bottom = bounds
    return (
        left + margin <= x
        and top + margin <= y
        and x + width + margin <= right
        and y + height + margin <= bottom
    )


def choose_hud_position_near_rect(
    rect: ScreenRect,
    width: int,
    height: int,
    bounds: ScreenBounds,
    *,
    margin: int = 8,
    gap_x: int = 18,
    gap_y: int = 10,
) -> tuple[int, int]:
    left, top, right, bottom = rect
    candidates = [
        (right + gap_x, bottom + gap_y),
        (left - width - gap_x, bottom + gap_y),
        (right + gap_x, top - height - gap_y),
        (left - width - gap_x, top - height - gap_y),
        (right + gap_x, top - 6),
        (left - width - gap_x, top - 6),
    ]
    for x, y in candidates:
        x = int(x)
        y = int(y)
        if fits_hud_position(x, y, width, height, bounds, margin=margin):
            return x, y

    best: tuple[int, int] | None = None
    best_penalty: int | None = None
    for x, y in candidates:
        clamped_x, clamped_y = clamp_hud_position(int(x), int(y), width, height, bounds, margin=margin)
        penalty = (clamped_x - int(x)) ** 2 + (clamped_y - int(y)) ** 2
        if best_penalty is None or penalty < best_penalty:
            best = (clamped_x, clamped_y)
            best_penalty = penalty
    if best is not None:
        return best
    return clamp_hud_position(right + gap_x, bottom + gap_y, width, height, bounds, margin=margin)


def is_reasonable_text_target_rect(
    rect: ScreenRect,
    bounds: ScreenBounds,
    *,
    window_rect: ScreenRect | None = None,
) -> bool:
    left, top, right, bottom = rect
    screen_left, screen_top, screen_right, screen_bottom = bounds
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return False
    if right <= screen_left or bottom <= screen_top or left >= screen_right or top >= screen_bottom:
        return False

    screen_width = max(1, screen_right - screen_left)
    screen_height = max(1, screen_bottom - screen_top)
    if width >= screen_width * 0.95 or height >= screen_height * 0.85:
        return False
    if width >= screen_width * 0.75 and height >= screen_height * 0.45:
        return False

    if window_rect is not None:
        window_left, window_top, window_right, window_bottom = window_rect
        window_width = max(1, window_right - window_left)
        window_height = max(1, window_bottom - window_top)
        if width >= window_width * 0.90 and height >= window_height * 0.70:
            return False
    return True
