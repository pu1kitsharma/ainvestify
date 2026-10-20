"""Private task ledger; task descriptions and dependencies are agent chosen."""
from .loop import ROLES

class TaskBoard:
    def __init__(self):
        self.tasks = {}

    def assign(self, task_id, role, instruction, dependencies=()):
        if task_id in self.tasks or role not in ROLES or not instruction.strip():
            raise ValueError('invalid task assignment')
        if any(item not in self.tasks for item in dependencies):
            raise ValueError('unknown dependency')
        self.tasks[task_id] = {'role': role, 'instruction': instruction,
                               'dependencies': list(dependencies), 'status': 'pending', 'returns': []}
        return self.status(task_id)

    def status(self, task_id):
        import copy
        return copy.deepcopy(self.tasks[task_id])

    def transition(self, task_id, status, reason=''):
        task = self.tasks[task_id]
        if status not in {'running', 'draft_complete', 'returned', 'blocked'}:
            raise ValueError('automated task ledger cannot approve release')
        if status == 'running' and any(self.tasks[item]['status'] != 'draft_complete' for item in task['dependencies']):
            raise ValueError('dependencies incomplete')
        if status == 'returned':
            if not reason.strip(): raise ValueError('return reason required')
            task['returns'].append(reason)
        task['status'] = status
        return self.status(task_id)
