# Prompting Notes

JoyBoy works best when prompts describe the intended change clearly and minimally.

## Editing prompts

Prefer direct instructions:

- `move the person to the left side`
- `keep the same person, change only the pose`
- `change the background to a brighter room`
- `make the jacket red`

## Pose prompts

Good examples:

- `change the pose, arms along the body`
- `hands on the face`
- `turn the body slightly to the left`
- `keep the same person and clothes, change only the pose`

## Repositioning prompts

Good examples:

- `move the person a little to the left`
- `place the subject farther back in the room`
- `keep the same camera angle, move the subject to the center`

## Prompt design tips

- say what should change
- say what must stay the same
- avoid long overloaded descriptions
- if identity matters, say `same person`
- if location matters, say `same room` or `same background`

## Reviewing saved prompt metadata

If you want to check the prompt or model used for a generated image or video later, open `Settings > Storage` and click the file card. The gallery viewer sidebar shows the saved `Model` and `Prompt` when that metadata exists.

## Router behavior

JoyBoy tries to detect:

- pose changes
- movement / repositioning
- clothing changes
- background edits
- identity preservation

The cleaner the instruction, the more stable the route selection.
