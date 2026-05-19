# Sync Coding Rules from Keel

You are syncing AI coding rules into this project using the `keel-sync.py` script from Project Keel. Your job is to locate or download the script, run it, and report the results.

## Step 1: Check prerequisites

Verify `python3` is available:

```bash
python3 --version
```

If not found, tell the user to install Python 3 and stop.

## Step 2: Locate the sync script

Try these in order — use the first one that works:

1. **`KEEL_PATH` env var** — if set, the script is at `$KEEL_PATH/scripts/keel-sync.py`
2. **Sibling directory** — look for `../keel/scripts/keel-sync.py` relative to this project
3. **Download** — fetch the script to a temp location:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/paulczar/keel/main/scripts/keel-sync.py -o /tmp/keel-sync.py
   ```

Set `SCRIPT` to the path of whichever you found.

## Step 3: Run the script

Build the command based on the arguments provided:

- **If an argument was provided** (a local path or URL):
  - If it looks like a URL (`https://...`): `python3 $SCRIPT --clone <arg>`
  - Otherwise: `python3 $SCRIPT --path <arg>`
- **If `KEEL_PATH` is set**: `python3 $SCRIPT --path $KEEL_PATH`
- **Otherwise**: `python3 $SCRIPT --clone https://github.com/paulczar/keel`

Always add `--force` so the script overwrites without prompting.

Run the command and capture the output.

## Step 4: Report results

Show the user the script output. Summarize:
- Which rules were selected and which were skipped
- Which output formats were generated
- That slash commands (keel-sync, keel-apply, etc.) were installed to `.cursor/commands/`, `.claude/commands/`, `.github/prompts/`
- How many files were written
- Any errors encountered
