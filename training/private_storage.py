"""Explicit approved local storage boundaries for confidential training derivatives."""
from pathlib import Path


def private_root(root, *, repo_root):
    """Resolve a deliberately supplied root outside the source checkout.

    The caller supplies the already approved storage location; this function does
    not grant source rights or validate OS access-control configuration.
    """
    if root is None:
        raise ValueError('An explicit outside-Git private root is required')
    result, repo = Path(root).resolve(), Path(repo_root).resolve()
    if (not result.is_dir() or result.is_relative_to(repo) or
            repo.is_relative_to(result)):
        raise ValueError('Private root must be an existing directory outside the repository')
    return result


def private_path(path, *, root, repo_root):
    boundary = private_root(root, repo_root=repo_root)
    result = Path(path).resolve()
    if result == boundary or not result.is_relative_to(boundary):
        raise ValueError('Private input and output must stay under the approved private root')
    return result
