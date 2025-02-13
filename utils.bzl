"""utils for the BUILD files.
"""

def get_repo_name():
    return Label("//:BUILD.bazel").workspace_name

def dedupe_and_ret_dicts(lst_one, lst_two):
    """Dedupe a list and make two dictionaries with that and another list

    Args:
        lst_one: First list. We dedupe this and use as keys.
        lst_two: Second list. We don't dedupe this and use as values.
    Returns:
        Two dictionaries. The first has the keys and values that are not dupes or the first instances of dupes.
        The second has the remaining keys and values that are dupes.
    """
    if len(lst_one) != len(lst_two):
        fail("Lists are not the same length: {} with len {} and {} with len {}".format(lst_one, len(lst_one), lst_two, len(lst_two)))
    dict_one = {}
    dict_two = {}

    for i in range(len(lst_one)):
        one_i = lst_one[i]
        two_i = lst_two[i]
        if one_i in dict_one.keys():
            if one_i in dict_two.keys():
                pass
            else:
                dict_two[one_i] = two_i
        else:
            dict_one[one_i] = two_i

    return dict_one, dict_two

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

def fix_module_name_in_paths(new_module_name, paths, suffix = "", old_module_name= ""):
    """Fix the paths to use the new module name to refer to it. 

       Some paths look like @@openssl+/:some/path/to/foo.txt.
       When they really are genfiles from the root of the new module in bazel-out.
       Like :some/path/to/foot.txt.

    Args:
        new_module_name: The new module name to replace with.
        paths: The paths to modify.
        suffix: The suffix of the files to replace. Default is replace all (empty string).
        old_module_name: The old module name to replace. Default is no module name (empty string).
    Returns:
        The fixed paths.
    """
    new_paths = []
    for old_path in paths:
        if suffix and suffix in old_path:
            if old_module_name in old_path:
                new_paths.append(old_path.replace(old_module_name, new_module_name))
            else:
                new_paths.append("{}//:{}".format(new_module_name, old_path))
        else:
            new_paths.append(old_path)
    return new_paths
