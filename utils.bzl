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
    final_list = []
    for thing in list_of_str:
        if thing in final_list:
            pass
        else:
            final_list.append(thing)
    print(final_list)
    return final_list

# Removes a .h and its .c if they exist as a pair
def remove_pairs_of_files(list_of_files):
    sorted_list = sorted(list_of_files)
    print(sorted_list)

    indicies_to_remove = []
    index = 0
    for file in sorted_list:
        if index + 1 == len(sorted_list):
            continue

        next_file = sorted_list[index + 1]

        file_wo_s_or_p = remove_file_suffix(file)
        next_file_wo_s_or_p = remove_file_suffix(next_file)

        if file_wo_s_or_p == next_file_wo_suffix:
            indicies_to_remove.append(index)
            indicies_to_remove.append(index + 1)

        index += 1
    print(indicies_to_remove)
    final_list = []
    index = 0
    for file in sorted_list:
        if index in indicies_to_remove:
            pass
        else:
            final_list.append(file)
        index += 1
    print(final_list)
    return final_list

def remove_file_suffix(file_name):
    if file_name.endswith(".h") or file_name.endswith(".c"):
        return file_name[:-2]

    return file_name
