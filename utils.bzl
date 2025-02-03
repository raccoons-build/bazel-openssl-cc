# Get the repository name from the BUILD file
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

# Deduplicate a list of strings
def dedupe(list_of_str):
    final_list = []
    for thing in list_of_str:
        if thing in final_list:
            pass
        else:
            final_list.append(thing)
    return final_list

# Removes a .h and its .c if they exist as a pair
def remove_pairs_of_files(list_of_files):
    no_suffix_or_prefix_lst = [remove_file_suffix_and_prefix(file_name) for file_name in list_of_files]
    sorted_list = sorted(no_suffix_or_prefix_lst)

    indicies_to_remove = []
    index = 0
    for file in sorted_list:
        if index + 1 == len(sorted_list):
            continue

        next_file = sorted_list[index + 1]

        if file == next_file:
            indicies_to_remove.append(index)
            indicies_to_remove.append(index + 1)

        index += 1
    final_list = []
    index = 0
    for file in sorted_list:
        if index in indicies_to_remove:
            pass
        else:
            final_list.append(file)
        index += 1
    return final_list

# Remove the suffix and prefix of a file name.
# e.g. some:/path/to/file_name.h --> file_name
def remove_file_suffix_and_prefix(file_name):
    if file_name.endswith(".h") or file_name.endswith(".c"):
        file_name = file_name[:-2]

    last_index_of_slash = 0
    index = 0
    for chr in file_name.elems():
        if chr == "/" or chr == "\\":
            last_index_of_slash = index
        index += 1
    return file_name[last_index_of_slash + 1:]
