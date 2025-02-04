"""utils for the BUILD files.
"""

def get_repo_name():
    return Label("//:BUILD.bazel").workspace_name

def dedupe(lst):
    """Dedupe a list

        Args:
            lst: A list of things
        Returns:
            The deuped list.
    """
    final_lst = []
    for thing in lst:
        if thing in final_lst:
            continue
        else:
            final_lst.append(thing)

    return final_lst
