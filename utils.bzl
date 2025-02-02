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
    return final_list

# Removes a .h and its .c if they exist as a pair
def remove_pairs_of_files(list_of_files):
    sorted = merge_sort(list_of_files)

    indicies_to_remove = []
    index = 0
    for file in sorted:
        if index + 1 == len(sorted):
            continue

        next_file = sorted[index + 1]

        file_wo_suffix = remove_file_suffix(file)
        next_file_wo_suffix = remove_file_suffix(next_file)

        if file_wo_suffix == next_file_wo_suffix:
            indicies_to_remove.append(index)
            indicies_to_remove.append(index + 1)

        index += 1
    final_list = []
    index = 0
    for file in sorted:
        if index in indicies_to_remove:
            pass
        else:
            final_list.append(file)
        index += 1
    return final_list

def remove_file_suffix(file_name):
    if file_name.endswith(".h") or file_name.endswith(".c"):
        return file_name[:-2]

    return file_name

# Merge function to merge two sorted lists using recursion
def merge(left, right):
    # Base cases: if one list is empty, return the other
    if len(left) == 0:
        return right
    if len(right) == 0:
        return left

    # Recursive case: compare the first elements of both lists
    if left[0] < right[0]:
        return [left[0]] + merge(left[1:], right)
    else:
        return [right[0]] + merge(left, right[1:])

# Merge sort function
def merge_sort(arr):
    if len(arr) <= 1:
        return arr
    mid = len(arr) // 2
    left = merge_sort(arr[:mid])
    right = merge_sort(arr[mid:])
    return merge(left, right)
