# 📝 TextFSM Best Practices

Use these rules to ensure high-accuracy parsing of new CLI commands.

## 📏 Template Structure
```text
Value Required Device (\S+)
Value Interface (\S+)
Value Status (up|down)

Start
  ^${Device}# show interface -> InterfaceSection

InterfaceSection
  ^${Interface}\s+is\s+${Status} -> Record
```

## 🚩 Common Regex Pitfalls
- **`^` and `$`**: Always use anchors to prevent matching middle-of-string fragments.
- **`Record`**: Do not forget to call `-> Record` or the parsed data will never be saved to the list.
- **Whitespace**: Use `\s+` instead of literal spaces to handle varying terminal formatting.

## 💡 Logic for Learner
- **Always** look for the repeating pattern (e.g., one block per interface).
- Use `Value Required` for fields that **must** exist for the row to be valid.
