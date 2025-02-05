# This script reads the OpenSSL meta-build system configuration output
# and converts into constants for the BUILD file.

use strict;

our %unified_info;
our %target;
our %config;

my %perlasm;

sub get_recursive_srcs_of_one {
    my ($initial_value, $value, %seen, %excludes) = @_;
    my %result;
    if (exists $seen{$value}) {
        return(%result);
    }
    if (exists $excludes{$value}) {
        return(%result);
    }
    $seen{$value} = ();
    my $srcs = $unified_info{sources}->{$value};
    my $deps = $unified_info{depends}->{$value};
    if (not ($srcs or $deps)) {
        $result{$value} = ();
    } elsif ($value =~ m/^.*\.c/) {
        $result{$value} = ();
    }
    foreach my $s (@$srcs) {
        %result = (%result, get_recursive_srcs_of_one($initial_value, $s, %seen));
    }
    foreach my $d (@$deps) {
        %result = (%result, get_recursive_srcs_of_one($initial_value, $d, %seen));
    }
    # Remove the initial value from the result (if it's there)
    # This breaks openssl app on Windows since it finds no
    # unique sources.
    delete $result{$initial_value};
    return(%result);
}

sub gather_libcrypto_srcs {
    my %srcs = get_recursive_srcs_of_one("libcrypto", "libcrypto");
    return(%srcs);
}

sub gather_libssl_srcs {
    my %seen;
    my $all = get_recursive_srcs_of_one("libssl", "libssl", %seen);
}

sub get_recursive_defines {
    my ($target, %excludes) = @_;
    my %defines;
    if (exists $excludes{$target}) {
        return %defines;
    }
    my $defs = $unified_info{defines}->{$target};
    foreach my $def (@$defs) {
        $defines{$def} = ();
    }
    foreach my $dep (@{$unified_info{depends}->{$target}}) {
        %defines = (%defines, get_recursive_defines($dep, %excludes));
    }
    return %defines;
}

my %libcrypto_srcs = get_recursive_srcs_of_one("libcrypto", "libcrypto");
my %excludes = %libcrypto_srcs;
my %libssl_srcs = get_recursive_srcs_of_one("libssl", "libssl", (), %excludes);
%excludes = (%excludes, %libssl_srcs);
my %openssl_app_srcs = get_recursive_srcs_of_one("apps/openssl", "apps/openssl", (), %excludes);

my %libcrypto_defines = get_recursive_defines("libcrypto");
my %libssl_defines = get_recursive_defines("libssl", ("libcrypto", 1));
my %openssl_app_defines = get_recursive_defines("apps/openssl", ("libcrypto", 1, "libssl", 1));

print "LIBCRYPTO_SRCS = [";
foreach (sort keys %libcrypto_srcs) {
    my $src = $_;
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        print '    "' . $src . '",';
    }
    if (exists($unified_info{generate}->{$src})) {
        if ($src =~ m/.*\.c$/ or $src =~m/.*\.h$/) {
            # FIXME -- it would be nice to generate build file magic to generate these files but for
            # now it is in the script that pulls the tar
        } else {
            $perlasm{$src} = ${unified_info{generate}->{$src}};
        }
    }
}
print "]\n";

print "LIBSSL_SRCS = [";
foreach my $src (sort keys %libssl_srcs) {
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        print '    "' . $src . '",';
    }
}
print "]\n";
print "OPENSSL_APP_SRCS = [";
foreach my $src (sort keys %openssl_app_srcs) {
    if (not $src =~ m/^.*\.asn1/ and not $src =~ m/^.*\.pm/) {
        print '    "' . $src . '",';
    }
}
print "]\n";
print "PERLASM_OUTS = [";
foreach (sort keys %perlasm) {
    print '    "' . $_ . '",';
}
print "]\n";
print "PERLASM_TOOLS = [";
foreach (sort values %perlasm) {
    print '    "' . @{$_}[0] . '",';
}
print "]\n";
print 'PERLASM_GEN = """';
foreach (sort keys %perlasm) {
    my $generation = $perlasm{$_};
    my @cmdlinebits;
    push(@cmdlinebits, $target{perlasm_scheme});
    if (@{$generation}[1,]) {
        push(@cmdlinebits, @{$generation}[1,]);
    }
    my $cmdline = join(" ", @cmdlinebits);
    print "\$(PERL) \$(location @{$generation}[0]) " . $cmdline . " \$(location $_);";
}
print '"""';
print "\n";

print "LIBCRYPTO_DEFINES = [";
foreach my $def (sort keys %libcrypto_defines) {
    print '    "-D'.$def.'",';
}
print "]";

print "LIBSSL_DEFINES = [";
foreach my $def (sort keys %libssl_defines) {
    print '    "-D'.$def.'",';
}
print "]";

print "OPENSSL_APP_DEFINES = [";
foreach my $def (sort keys %openssl_app_defines) {
    print '    "-D'.$def.'",';
}
print "]";

my @defines;
if (exists $target{defines}) {
    push @defines, @{$target{defines}}
}
if (exists $config{defines}) {
    push @defines, @{$config{defines}}
}
if (exists $config{lib_defines}) {
    push @defines, @{$config{lib_defines}}
}
if (exists $config{openssl_other_defines}) {
    push @defines, @{$config{openssl_other_defines}}
}

print "OPENSSL_DEFINES = [";
foreach (sort @defines) {
    print '    "-D', $_, '",';
}
print "]\n";