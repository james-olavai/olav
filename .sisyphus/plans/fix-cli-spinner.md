# Work Plan: Fix CLI Streaming Display Artifacts

## Goal
Eliminate "stacked" spinners and artifacts in the CLI output by refactoring `StreamingDisplay` to use a single persistent `rich.live.Live` object with proper lifecycle management.

## Context
The current implementation creates a NEW `Live` object every time `show_processing_status` is called. This causes multiple "Thinking..." lines to stack up in the terminal because the previous `Live` object is never updated or stopped correctly before a new one starts.

## Strategy
1.  **Single Persistent Instance**: Maintain a single `self._live` attribute in `StreamingDisplay`.
2.  **Transient Mode**: Use `transient=True` so the spinner disappears from history when stopped.
3.  **Update vs. Create**:
    *   If `self._live` exists: `update()` it with the new message.
    *   If `self._live` is None: Create and `start()` it.
4.  **Automatic "Print Above"**: Use `self.console.print` (which `Live` respects) to print logs/tools above the active spinner.

---

## TODOs

### Phase 1: StreamingDisplay Refactor (`src/olav/cli/display.py`)

- [ ] 1. **Initialize `self._live`**
  - Update `StreamingDisplay.__init__` to initialize `self._live = None`.
  - Remove `self._current_spinner` (it's being replaced).

- [ ] 2. **Refactor `show_processing_status`**
  - Change logic to reuse `self._live`.
  - If `self._live` is active: Call `self._live.update(Spinner(...))`.
  - If `self._live` is None: Create `Live(Spinner(...), console=self.console, transient=True, refresh_per_second=4)`, assign to `self._live`, and call `start()`.

- [ ] 3. **Refactor `stop_processing_status`**
  - If `self._live` is active: Call `self._live.stop()`.
  - Set `self._live = None`.

### Phase 2: Verification

- [ ] 4. **Verify CLI Output**
  - Run `uv run olav` and execute a query (e.g., "list all devices").
  - Confirm "Thinking..." spinner appears at the bottom.
  - Confirm tool executions (e.g., `Executing task...`) appear *above* the spinner.
  - Confirm spinner disappears (transient) when done.
  - Confirm no stacked "Thinking..." lines.

---

## Technical Details

**Code Pattern for `show_processing_status`:**
```python
def show_processing_status(self, message: str = "Processing...") -> None:
    if self.quiet:
        return

    from rich.live import Live
    from rich.spinner import Spinner

    spinner = Spinner("dots", text=f"[bold green]{message}[/bold green]")

    if self._live:
        self._live.update(spinner, refresh=True)
    else:
        self._live = Live(spinner, console=self.console, transient=True, refresh_per_second=4)
        self._live.start()
```

**Code Pattern for `stop_processing_status`:**
```python
def stop_processing_status(self) -> None:
    if self._live:
        self._live.stop()
        self._live = None
```
