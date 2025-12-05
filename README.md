# Pending Task Bot

A simple command-line task management bot written in Python.

## Features

- Add new tasks
- List pending tasks
- List all tasks (including completed)
- Mark tasks as completed
- Remove individual tasks
- Clear all completed tasks
- Persistent storage using JSON

## Requirements

- Python 3.6 or higher

## Installation

1. Clone the repository:
```bash
git clone https://github.com/19yananda-cloud/pending-task-in-bot.git
cd pending-task-in-bot
```

2. Make the script executable (optional):
```bash
chmod +x task_bot.py
```

## Usage

Run the bot:
```bash
python3 task_bot.py
```

### Available Commands

- `add <description>` - Add a new task
- `list` - List all pending tasks
- `list all` - List all tasks (including completed)
- `complete <id>` - Mark a task as completed
- `remove <id>` - Remove a task by ID
- `clear` - Remove all completed tasks
- `quit` or `exit` - Exit the bot

### Examples

```
> add Buy groceries
Task added: Buy groceries (ID: 1)

> add Write documentation
Task added: Write documentation (ID: 2)

> list

=== Pending Tasks ===
○ [1] Buy groceries
○ [2] Write documentation

> complete 1
Task 1 marked as completed: Buy groceries

> list

=== Pending Tasks ===
○ [2] Write documentation

> list all

=== All Tasks ===
✓ [1] Buy groceries
○ [2] Write documentation

> clear
Removed 1 completed task(s).

> quit
Goodbye!
```

## Data Storage

Tasks are stored in a `tasks.json` file in the same directory as the script. This file is created automatically when you add your first task.

## License

This project is open source and available under the MIT License.