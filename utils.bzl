"""utils for the BUILD files.
"""

def get_repo_name():
    return Label("//:BUILD.bazel").workspace_name

# Function to convert a .c file name to a .h file name
def convert_c_to_h(c_file_name):
    if c_file_name.endswith(".c"):
        # Replace .c with .h
        h_file_name = c_file_name[:-2] + ".h"
        return h_file_name
    else:
        # Return the same name if it's not a .c file
        return c_file_name

# Function that takes a src and makes it work as a build rule name
def to_build_rule_name(file_name):
    return file_name.replace("/", "_").replace(":", "_").replace(".", "_")

# Function that takes a src and makes it work as a target name
def to_target_name(file_name):
    return file_name.replace(":", "")

def dedupe(list_of_str):
    """ Deduplicate a list of strings

        Args:
            list_of_str: the list of strings to dedupe.
        Returns:
            The list deduped.
    """
    final_list = []
    for thing in list_of_str:
        if thing in final_list:
            pass
        else:
            final_list.append(thing)
    return final_list

def remove_pairs_of_files(list_of_files):
    """ Removes a .h and its .c if they exist as a pair

        Args:
            list_of_files: the list of files to removes pairs and dupes.
        Returns:
            The list of files with pairs and dupes removed.
    """
    no_suffix_or_prefix_list = [remove_file_suffix_and_prefix(file_name) for file_name in list_of_files]
    indicies_to_remove = []
    index = 0
    for file in no_suffix_or_prefix_list:
        rest_of_list = no_suffix_or_prefix_list[index + 1:]
        if file in rest_of_list:
            indicies_to_remove.append(index)
        index += 1
    final_list = []
    index = 0
    print(indicies_to_remove)
    for file in list_of_files:
        if index in indicies_to_remove:
            pass
        else:
            final_list.append(file)
        index += 1
    print(final_list)
    return final_list

def remove_file_suffix_and_prefix(file_name):
    """ Remove the suffix and prefix of a file name.

        e.g. some:/path/to/file_name.h --> file_name
        Args:
            file_name: the name of the file to strip.
        Returns:
            The stripped file name.
    """
    if file_name.endswith(".h") or file_name.endswith(".c"):
        file_name = file_name[:-2]

    last_index_of_slash = 0
    index = 0
    for chr in file_name.elems():
        if chr == "/" or chr == "\\":
            last_index_of_slash = index
        index += 1
    return file_name[last_index_of_slash + 1:]
