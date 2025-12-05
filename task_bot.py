#!/usr/bin/env python3
"""
Pending Task Bot - A simple command-line task management bot
"""

import json
import os
from datetime import datetime


class TaskBot:
    """A simple bot to manage pending tasks"""
    
    def __init__(self, data_file='tasks.json'):
        self.data_file = data_file
        self.tasks, self.next_id = self.load_tasks()
    
    def load_tasks(self):
        """Load tasks from the JSON file"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    # Support both old and new format
                    if isinstance(data, list):
                        # Old format: just a list of tasks
                        tasks = data
                        # Calculate next_id from existing tasks
                        next_id = max((task['id'] for task in tasks), default=0) + 1
                        return tasks, next_id
                    # New format: dict with next_id and tasks
                    return data.get('tasks', []), data.get('next_id', 1)
            except (json.JSONDecodeError, KeyError, ValueError):
                return [], 1
        return [], 1
    
    def save_tasks(self):
        """Save tasks to the JSON file"""
        data = {
            'next_id': self.next_id,
            'tasks': self.tasks
        }
        temp_file = self.data_file + '.tmp'
        try:
            # Write to a temporary file first
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            # Atomic rename to avoid corruption
            os.replace(temp_file, self.data_file)
        except (IOError, OSError) as e:
            # Clean up temp file if it exists
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
            raise IOError(f"Failed to save tasks: {e}") from e
    
    def add_task(self, description):
        """Add a new task"""
        task = {
            'id': self.next_id,
            'description': description,
            'completed': False,
            'created_at': datetime.now().isoformat()
        }
        self.tasks.append(task)
        self.next_id += 1
        self.save_tasks()
        return f"Task added: {description} (ID: {task['id']})"
    
    def list_tasks(self, show_all=False):
        """List all tasks or only pending tasks"""
        if not self.tasks:
            return "No tasks found."
        
        result = []
        if show_all:
            result.append("\n=== All Tasks ===")
        else:
            result.append("\n=== Pending Tasks ===")
        
        for task in self.tasks:
            if show_all or not task['completed']:
                status = "✓" if task['completed'] else "○"
                result.append(f"{status} [{task['id']}] {task['description']}")
        
        if not any(not t['completed'] for t in self.tasks) and not show_all:
            return "No pending tasks! 🎉"
        
        return "\n".join(result)
    
    def complete_task(self, task_id):
        """Mark a task as completed"""
        for task in self.tasks:
            if task['id'] == task_id:
                if task['completed']:
                    return f"Task {task_id} is already completed."
                task['completed'] = True
                task['completed_at'] = datetime.now().isoformat()
                self.save_tasks()
                return f"Task {task_id} marked as completed: {task['description']}"
        return f"Task {task_id} not found."
    
    def remove_task(self, task_id):
        """Remove a task"""
        for i, task in enumerate(self.tasks):
            if task['id'] == task_id:
                description = task['description']
                self.tasks.pop(i)
                self.save_tasks()
                return f"Task {task_id} removed: {description}"
        return f"Task {task_id} not found."
    
    def clear_completed(self):
        """Remove all completed tasks"""
        completed_count = sum(1 for task in self.tasks if task['completed'])
        if completed_count == 0:
            return "No completed tasks to remove."
        self.tasks = [task for task in self.tasks if not task['completed']]
        self.save_tasks()
        return f"Removed {completed_count} completed task(s)."


def main():
    """Main function to run the task bot"""
    bot = TaskBot()
    
    print("=" * 50)
    print("  Pending Task Bot")
    print("=" * 50)
    print("\nCommands:")
    print("  add <description>  - Add a new task")
    print("  list              - List pending tasks")
    print("  list all          - List all tasks")
    print("  complete <id>     - Mark task as completed")
    print("  remove <id>       - Remove a task")
    print("  clear             - Remove all completed tasks")
    print("  quit              - Exit the bot")
    print("=" * 50)
    
    while True:
        try:
            command = input("\n> ").strip()
            
            if not command:
                continue
            
            parts = command.split(maxsplit=1)
            cmd = parts[0].lower()
            
            if cmd == 'quit' or cmd == 'exit':
                print("Goodbye!")
                break
            
            elif cmd == 'add':
                if len(parts) < 2:
                    print("Usage: add <description>")
                else:
                    print(bot.add_task(parts[1]))
            
            elif cmd == 'list':
                show_all = len(parts) > 1 and parts[1].lower() == 'all'
                print(bot.list_tasks(show_all))
            
            elif cmd == 'complete':
                if len(parts) < 2:
                    print("Usage: complete <id>")
                else:
                    try:
                        task_id = int(parts[1])
                        print(bot.complete_task(task_id))
                    except ValueError:
                        print("Error: Task ID must be a number")
            
            elif cmd == 'remove':
                if len(parts) < 2:
                    print("Usage: remove <id>")
                else:
                    try:
                        task_id = int(parts[1])
                        print(bot.remove_task(task_id))
                    except ValueError:
                        print("Error: Task ID must be a number")
            
            elif cmd == 'clear':
                print(bot.clear_completed())
            
            else:
                print(f"Unknown command: {cmd}")
                print("Type 'quit' to exit or use one of the available commands.")
        
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == '__main__':
    main()
