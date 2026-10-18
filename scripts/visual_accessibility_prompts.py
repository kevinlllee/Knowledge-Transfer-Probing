"""Complete VLM judging prompts for the seven tasks."""

# Send the rendered prompt and the generated image together to the VLM.
# Each prompt specifies visual checks and a JSON response format containing
# observations or judgments with a brief explanation for downstream scoring.
#
# Required template fields:
#   color: char ("R"), char_label_en ("uppercase R"), color ("blue")
#   count: item_plural ("apples"), item_singular ("apple")
#   shape: shape ("triangle")
#   number, size, spatial, text: no fields
# Use build_prompt(task, **fields) to fill the $field placeholders.

from string import Template


# Check the target character and its expected color.
COLOR_PROMPT = """You are an image quality inspector. Check whether the image below satisfies ALL of the following checks:
1. The main subject of the image is the character "$char" ($char_label_en), clearly recognizable;
2. The character reads overall as clearly $color; natural shading, highlights and texture from lighting, material or art style are acceptable, but no part of the character may distinctly show a different color, and the overall color must not be mistakable for any color other than $color;
3. A few unrelated small letters may appear at the image edges or in the background. They are acceptable as long as they remain minor, incidental details and do not prevent the target character from being the clear, dominant subject;
4. The character's color contrasts clearly with the background and cannot be mistaken for another color.

Output only one JSON object of the form {"pass": true/false, "reason": "brief explanation"}. pass=true only if ALL checks are satisfied; if any check fails, output pass=false and explain in reason."""


# Independently count the target objects without supplying the expected count.
COUNT_PROMPT = """Inspect the attached image of $item_plural. Do not assume or guess an intended quantity. Determine the quantity solely by independently counting what is visibly present.

Checks:
- Independently count only the actual physical $item_plural visible in the image;
- Every counted $item_singular is completely inside the frame, clearly distinguishable, and not hidden or overlapped;
- The target objects are the dominant subject and can be counted confidently at a glance;
- The setting is a plausible everyday scene without reflections, pictures, or decorations that could be mistaken for additional target objects.

Output only one JSON object with this schema: {"observed_count": <integer or null>, "easy_to_count": true/false, "all_fully_visible": true/false, "no_overlap": true/false, "target_is_main_subject": true/false, "reasonable_scene": true/false, "reason": "brief observation"}. Use null when a confident count is impossible."""


# Independently read the printed player name and jersey number.
NUMBER_PROMPT = """Inspect the attached image of the back of one sports jersey. This is an edited image placing the jersey in an everyday lifestyle scene. Independently read the player name and the jersey number printed on the back. Do not infer any text from prior knowledge or guess an intended value; report only the characters actually visible. If the name or the number is uncertain, partially hidden, or ambiguous, use null rather than guessing.

Checks:
- The edited image places the same jersey in one plausible everyday lifestyle scene while its printed back stays toward the camera;
- Exactly one jersey is shown from the back, large, fully visible, and unobstructed, with nothing else in the image that duplicates its lettering;
- The printed name and number are upright, not mirrored or distorted, and readable at a glance, with the number showing no leading zero;

Output only one JSON object with exactly this schema: {"observed_player_name": "exact visible name" or null, "observed_jersey_number": <integer> or null, "reason": "brief visual evidence, noting any failed check"}."""


# Observe the badge outline and compare it with the expected shape.
SHAPE_PROMPT = """Inspect the attached image of a badge. This is an edited image that places the badge into an everyday scene. First independently identify the badge's visible overall outline shape, then compare that observation with the expected target shape "$shape". Do not infer the observed shape merely from the expected answer.

Checks:
- The image contains exactly one badge, with no other badge, medal, or pin;
- The badge is completely inside the frame, unobstructed, and its complete outer boundary is visible;
- The badge's overall outline shape is immediately and confidently identifiable at a glance, without relying on a label or guess;
- The observed outline shape matches the expected target shape exactly;
- No prominent competing object makes the badge's outline ambiguous.

Output only one JSON object with this schema: {"observed_shape": "triangle|square|pentagon|five-pointed star|circle|other|unclear", "shape_easy_to_identify": true/false, "matches_expected_shape": true/false, "exactly_one_badge": true/false, "badge_fully_visible": true/false, "recognizable_as_badge": true/false, "reason": "brief visual evidence"}."""


# Independently read map text and identify the larger country.
SIZE_PROMPT = """Inspect the attached image of one fictional two-country regional map. This is a style-edited version of the map. Read all visible map text independently and determine the larger country solely from the visible land areas. Do not infer any title, country name, or size relationship from prior knowledge. If any text or the relative-size judgment is uncertain, use null rather than guessing.

Checks:
- The edited image uses one coherent cartographic art style while remaining a clear front-facing map;
- There is exactly one complete regional map containing exactly two countries; both complete country outlines are fully visible, and all mapped area outside them is ocean, with no third territory, island, inset, disputed zone, lake, or unlabeled land;
- The map title is present and easy to read;
- Both country names are present, spelled legibly, and unambiguously attached to their respective countries;
- The map title and both country labels are sufficiently large, upright, high contrast, unobstructed, and easy to read at normal viewing size;
- Every coastline and both complete country outlines are crisp and easy to follow;
- The two country areas differ so clearly that the larger country can be identified immediately and confidently, without close measurement or guessing;
- The whole map is front-facing, fully inside the frame, unobstructed, and not cropped, rotated, mirrored, flipped, skewed, or distorted;
- No text other than the one map title and two country names is present;

Output only one JSON object with exactly this schema: {"observed_map_title": "exact visible title" or null, "observed_country_names": ["exact first visible country name", "exact second visible country name"] or null, "observed_larger_country": "exact visible name of the larger country" or null, "exactly_two_countries": true/false, "map_fully_visible": true/false, "no_extra_map_content": true/false, "reason": "brief visual evidence"}."""


# Independently report stripe orientation and the complete color order.
SPATIAL_PROMPT = """Inspect the attached image of one national flag. This is an edited image placing the flag in an everyday lifestyle scene. Independently report the flag's visible stripe orientation and ordered colors. Do not infer any answer from a country name or prior knowledge. If the stripes are vertical, report colors from left to right; if horizontal, report colors from top to bottom. If any color, orientation, or order is uncertain, use null rather than guessing.

Checks:
- This is the national flag of a fictional MagicWorld country. Do not compare it with, identify it as, or judge it against any real-world country's flag;
- There is exactly one simple rectangular national flag with exactly three equal solid-color design stripes and no emblem, seal, border, text, or extra pattern, apart from the permitted flagpole sleeve described below;
- A narrow, elongated white sleeve or channel may appear along the flag's left or top outer edge so that a flagpole can pass through it. This mounting feature is allowed and must not cause the image to fail. Do not treat it as a design stripe, border, extra pattern, obstruction, or extra color, and ignore it when judging stripe count or equality, orientation, ordered colors, visibility, and the flag's landscape aspect ratio;
- The complete flag is large, dominant, fully inside the frame, unobstructed, and not hidden by folds, glare, shadows, or other objects;
- The flag itself has a landscape rectangular format: its visible width is clearly greater than its visible height. Judge the flag's overall bounds, not its stripe orientation;
- Each of the three colors is easy to identify confidently, with no strong lighting tint, ambiguous shade, gradient, or blended boundary;
- The stripe orientation and the full three-color order are immediately readable;
- The flag is front-facing and has not been rotated, mirrored, flipped, reversed, or otherwise reoriented;

Output only one JSON object with this schema: {"observed_orientation": "vertical|horizontal|unclear", "observed_color_order": ["black|white|red|yellow|blue|green", "black|white|red|yellow|blue|green", "black|white|red|yellow|blue|green"] or null, "exactly_three_equal_stripes": true/false, "colors_easy_to_identify": true/false, "order_easy_to_identify": true/false, "flag_is_main_subject": true/false, "flag_fully_visible": true/false, "flag_is_landscape": true/false, "flag_not_rotated_or_flipped": true/false, "reason": "brief visual evidence"}."""


# Independently read the book title and author name.
TEXT_PROMPT = """Inspect the attached image of the front cover of one closed book. This is an edited image placing the book in an everyday lifestyle scene. Independently read the book title and the author name printed on the cover. Do not infer any text from prior knowledge or guess an intended value; report only the characters actually visible. If the title or the author name is uncertain, partially hidden, or ambiguous, use null rather than guessing.

Checks:
- The edited image places the same book in one plausible everyday lifestyle scene while its printed front cover stays toward the camera;
- Exactly one book is shown, large, fully visible, and unobstructed, with no other book anywhere in the image;
- The printed title and author line are upright, not mirrored or distorted, and the title is readable at a glance;

Output only one JSON object with exactly this schema: {"observed_book_title": "exact visible title" or null, "observed_author_name": "exact visible author name" or null, "reason": "brief visual evidence, noting any failed check"}."""


PROMPTS = {
    "color": COLOR_PROMPT,
    "count": COUNT_PROMPT,
    "number": NUMBER_PROMPT,
    "shape": SHAPE_PROMPT,
    "size": SIZE_PROMPT,
    "spatial": SPATIAL_PROMPT,
    "text": TEXT_PROMPT,
}


def build_prompt(task: str, **fields: str) -> str:
    """Render a task prompt; missing required fields raise KeyError.

    Example:
        build_prompt("color", char="R", char_label_en="uppercase R", color="blue")
    """
    return Template(PROMPTS[task]).substitute(fields)
