"""utils for the BUILD files.
"""

def get_repo_name():
    return Label("//:BUILD.bazel").workspace_name

def dedupe(lst):
    """Dedupe a list

        Args:
            lst: A list of things
        Return:
            The deuped list.
    """
    final_lst = []
    for thing in lst:
        if thing in final_lst:
            continue
        else:
            final_lst.append(thing)

    return final_lst

def fix_paths_for_windows(path_lst):
    """Replace the \\ with / on Windows.

        We need them to be the opposite way when writing the generated bzl files on Windows.
        But when we use the files we need to fix the paths.
        Args:
            path_lst: The list of paths to fix.
        Return:
            The fixed path list.
    """
    return [fix_path_for_windows_in_str(path) for path in path_lst]

def fix_path_for_windows_in_str(str):
    """Replace the \\ with / on Windows.

        We need them to be the opposite way when writing the generated bzl files on Windows.
        But when we use the files we need to fix the paths.
        Args:
            str: The string to fix.
        Return:
            The fixed string.
    """
    return str.replace("\\", "/")

def modify_names_for_dupes(path_lst):
    """Add a number to the end of the path to the path so that we can remove it later.

       This is to keep dupes and trick bazel.

       Args:
            path_lst: The list of paths to fix
       Returns:
            The fixed path list
    """
    seen_paths = []
    i = 0
    for path in path_lst:
        if path in seen_paths:
            seen_paths.append("{}_{}".format(path, i))
            i += 1
        else:
            seen_paths.append(path)

    return seen_paths
