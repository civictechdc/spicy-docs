# Maintain the documentation

Update the guide that owns the changed behavior:

| Change | Home |
| --- | --- |
| Files, imports or responsibilities | [Architecture](architecture.md) |
| Commands, outputs or failures | [Commands](cli.md), [scripts](../scripts/README.md) or [tools](../tools/README.md) |
| Source scope, evidence or identity | Its [source guide](README.md#work-on-a-source) |
| Release requirements | [Release guide](releases.md) and [specification](superpowers/specs/2026-08-25-source-native-release-spec.md) |
| A durable reason or ownership choice | [Decisions](decisions.md) or [ownership](source-ownership.md) |

## Make it easy to scan

- Lead with the task and result. Use short sections and one point per bullet.
- Give each rule one home; link to detail instead of repeating it.
- Keep commands complete: inputs, credentials, effects and expected output.
- Keep comments for intent, constraints and surprising behavior. Put the reason
  beside the branch; omit narration of obvious code.
- Describe current behavior in guides. Keep proposed requirements and measured
  results clearly labeled; preserve exact source and format terms.
- Use Git for completed-work chronology. Keep large captures and measurements
  with their input pins, command and corpus receipts.

Read the implementation and tests before promising behavior. Check paths and
anchors when moving content. Run repository Python examples through `uv run --frozen`.

## Former generated wiki

The wiki was consolidated into task guides in September 2026. Its generator
command/configuration were not retained; its metadata and full text remain at
commit `720fabd6c2aae4e1a692ff721cbaca5e55f70256`:

```sh
git show 720fabd6c2aae4e1a692ff721cbaca5e55f70256:wiki/metadata.json
git show 720fabd6c2aae4e1a692ff721cbaca5e55f70256:wiki/federal_register_source_native.md
```

Use current source guides for behavior; the historical wiki includes superseded rules.
