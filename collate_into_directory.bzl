"""Move files from one path to an output directory specified through a series of dicts
"""

def _build_manifest_content(srcs_map, ctx, outdir):
    """Builds the manifest content for the collate_into_directory binary.

    Args:
        srcs_map: map of sources to the prefix to strip.
        ctx: the current context.
        outdir: the output directory.
    Returns:
        input_files: depset of input files.
        manifest_content: tab-separated manifest string (dest_dir\\tfile\\tprefix per line).
    """
    manifest_lines = []
    for (tgt, prefix) in srcs_map.items():
        output_prefix = None
        if tgt in ctx.attr.outs_prefix_map:
            output_prefix = ctx.attr.outs_prefix_map[tgt]

        for file in tgt[DefaultInfo].files.to_list():
            outdir_path = outdir.path if not output_prefix else "{}/{}".format(outdir.path, output_prefix.lstrip("/"))
            prefix_to_strip = prefix if not file.path.startswith(ctx.genfiles_dir.path) else "{}/{}".format(ctx.genfiles_dir.path, prefix)

            manifest_lines.append("{}\t{}\t{}".format(outdir_path, file.path, prefix_to_strip))

    input_files = depset(
        transitive = [tgt[DefaultInfo].files for tgt in srcs_map.keys()],
    )

    return input_files, "\n".join(manifest_lines) + "\n"

def _collate_into_directory_impl(ctx):
    outdir = ctx.actions.declare_directory("{}_out".format(ctx.attr.name))

    srcs_map = dict(ctx.attr.srcs_prefix_map)

    implicit_srcs_from_outs = {
        tgt: ""
        for (tgt, _) in ctx.attr.outs_prefix_map.items()
        if tgt not in srcs_map
    }
    srcs_map.update(implicit_srcs_from_outs)

    input_files, manifest_content = _build_manifest_content(srcs_map, ctx, outdir)

    manifest = ctx.actions.declare_file("{}.manifest".format(ctx.label.name))
    ctx.actions.write(
        output = manifest,
        content = manifest_content,
    )

    ctx.actions.run(
        inputs = depset([manifest], transitive = [input_files]),
        executable = ctx.executable._generator,
        arguments = [manifest.path],
        outputs = [outdir],
        mnemonic = "OpenSSLCopyFilesToDir",
        progress_message = "Copying files to directory",
    )

    return [
        DefaultInfo(
            files = depset([outdir]),
            runfiles = ctx.runfiles(files = [outdir]),
        ),
    ]

collate_into_directory = rule(
    implementation = _collate_into_directory_impl,
    doc = "Collate a set of files into a single directory, optionally manipulating subdirectories.",
    attrs = {
        "outs_prefix_map": attr.label_keyed_string_dict(
            allow_files = True,
            doc = "Map from target that provides files to prefix to use when placing the files, in addition to the relative directory remaining after stripping the prefix. If a key appears in this map but not the `srcs_prefix_map`, it will be implicitly added as a source.",
        ),
        "srcs_prefix_map": attr.label_keyed_string_dict(
            allow_files = True,
            doc = "Map from target that provides files to prefix to strip from those files.",
        ),
        "_generator": attr.label(
            allow_single_file = True,
            executable = True,
            cfg = "exec",
            default = Label("@openssl-generated-overlay//:collate_into_directory"),
        ),
    },
)
