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

def fix_windows_spaces(str):
    """Surround words with spaces in them in a path with quotes on Windows.

        Args:
            str: The string to fix.
        Return:
            The fixed string.
    """
    print(str)
    # Split the path by slashes
    parts = str.split("/")

    # Iterate over each part and add quotes if it contains spaces
    quoted_parts = []
    for part in parts:
        if " " in part:  # Check if the word contains a space
            quoted_parts.append('"' + part + '"')
        else:
            quoted_parts.append(part)

    # Join the parts back into a single string with slashes
    return "/".join(quoted_parts)
