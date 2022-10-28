from conan import ConanFile
from conan.tools.files import rmdir, copy, rename, rm
from conan.tools.build import check_min_cppstd
from conan.tools.scm import Git, Version
from conan.tools.layout import basic_layout
from conan.tools.microsoft import is_msvc
from conan.tools.microsoft import MSBuild, VCVars
from conan.tools.gnu import Autotools, AutotoolsToolchain
from conan.errors import ConanInvalidConfiguration
from pathlib import Path
import os

required_conan_version = ">=1.50.0"


class bimgConan(ConanFile):
    name = "bimg"
    license = "BSD-2-Clause"
    homepage = "https://github.com/bkaradzic/bimg"
    url = "https://github.com/RazielXYZ/bimg-conan"
    description = "Cross-platform, graphics API agnostic, \"Bring Your Own Engine/Framework\" style rendering library."
    topics = ("lib-static", "C++", "C++14", "rendering", "utility")
    settings = "os", "compiler", "arch", "build_type"
    options = {"tools": [True, False]}
    default_options = {"tools": False}

    requires = "bx/[>=1.18.0]@bx/rolling"

    invalidPackageExceptionText = "Less lib files found for copy than expected. Aborting."
    expectedNumLibs = 3
    bxFolder = "bx"
    bimgFolder = "bimg"

    vsVerToGenie = {"17": "2022", "16": "2019", "15": "2017",
                    "193": "2022", "192": "2019", "191": "2017"}

    gccOsToGenie = {"Windows": "--gcc=mingw-gcc", "Linux": "--gcc=linux-gcc", "Macos": "--gcc=osx", "Android": "--gcc=android", "iOS": "--gcc=ios"}
    gmakeOsToProj = {"Windows": "mingw", "Linux": "linux", "Macos": "osx", "Android": "android", "iOS": "ios"}
    gmakeArchToGenieSuffix = {"x86": "-x86", "x86_64": "-x64", "armv8": "-arm64", "armv7": "-arm"}
    osToUseArchConfigSuffix = {"Windows": False, "Linux": False, "Macos": True, "Android": True, "iOS": True}

    buildTypeToMakeConfig = {"Debug": "config=debug", "Release": "config=release"}
    archToMakeConfigSuffix = {"x86": "32", "x86_64": "64"}
    osToUseMakeConfigSuffix = {"Windows": True, "Linux": True, "Macos": False, "Android": False, "iOS": False}

    def layout(self):
        basic_layout(self, src_folder=".")

    def package_id(self):
        if is_msvc(self):
            del self.info.settings.compiler.cppstd

    def configure(self):
        if self.settings.os == "Windows":
            self.libExt = ["*.lib", "*.pdb"]
            self.binExt = ["*.exe"]
            self.libTargetPrefix = "libs\\"
            self.toolTargetPrefix = "tools\\"
            self.packageLibPrefix = ""
            self.binFolder = "windows"
        elif self.settings.os in ["Linux", "FreeBSD"]:
            self.libExt = ["*.a"]
            self.binExt = []
            self.libTargetPrefix = ""
            self.toolTargetPrefix = ""
            self.packageLibPrefix = "lib"
            self.binFolder = "linux"
        elif self.settings.os == "Macos":
            self.libExt = ["*.a"]
            self.binExt = []
            self.libTargetPrefix = ""
            self.toolTargetPrefix = ""
            self.packageLibPrefix = "lib"
            self.binFolder = "darwin"

        self.projs = [f"{self.libTargetPrefix}bimg", f"{self.libTargetPrefix}bimg_decode", f"{self.libTargetPrefix}bimg_encode"]
        self.genieExtra = ""
        if self.options.tools:
            self.genieExtra += " --with-tools"
            self.projs.extend([f"{self.toolTargetPrefix}texturec"])

    def set_version(self):
        self.output.info("Setting version from git.")
        rmdir(self, self.bimgFolder)
        git = Git(self, folder=self.bimgFolder)
        git.clone(f"{self.homepage}.git", target=".")

        # Hackjob semver! Versioning by commit seems rather annoying for users, so let's version by commit count
        numCommits = int(git.run("rev-list --count master"))
        verMajor = 1 + (numCommits // 10000)
        verMinor = (numCommits // 100) % 100
        verRev = numCommits % 100
        self.output.highlight(f"Version {verMajor}.{verMinor}.{verRev}")
        self.version = f"{verMajor}.{verMinor}.{verRev}"

    def validate(self):
        if self.settings.compiler.get_safe("cppstd"):
            check_min_cppstd(self, 14)
        if Version(self.version) < "1.3.30" and self.settings.os in ["Linux", "FreeBSD"] and self.settings.arch == "x86_64" and self.settings_build.arch == "x86":
            raise ConanInvalidConfiguration("This version of the package cannot be cross-built to Linux x86 due to old astc breaking that.")

    def source(self):
        # bimg requires bx source to build;
        self.output.info("Getting source")
        gitBx = Git(self, folder=self.bxFolder)
        gitBx.clone("https://github.com/bkaradzic/bx.git", target=".")
        gitBimg = Git(self, folder=self.bimgFolder)
        gitBimg.clone(f"{self.homepage}.git", target=".")

    def generate(self):
        if is_msvc(self):
            tc = VCVars(self)
            tc.generate()
        else:
            tc = AutotoolsToolchain(self)
            tc.generate()

    def build(self):
        # Map conan compilers to genie input
        self.bxPath = os.path.join(self.source_folder, self.bxFolder)
        self.bimgPath = os.path.join(self.source_folder, self.bimgFolder)
        genie = os.path.join(self.bxPath, "tools", "bin", self.binFolder, "genie")
        if is_msvc(self):
            # Use genie directly, then msbuild on specific projects based on requirements
            genieVS = f"vs{self.vsVerToGenie[str(self.settings.compiler.version)]}"
            genieGen = f"{self.genieExtra} {genieVS}"
            self.run(f"{genie} {genieGen}", cwd=self.bimgPath)

            # Build with MSBuild
            msbuild = MSBuild(self)
            # customize to Release when RelWithDebInfo
            msbuild.build_type = "Debug" if self.settings.build_type == "Debug" else "Release"
            # use Win32 instead of the default value when building x86
            msbuild.platform = "Win32" if self.settings.arch == "x86" else msbuild.platform
            msbuild.build(os.path.join(self.bimgPath, ".build", "projects", genieVS, "bimg.sln"), targets=self.projs)            
        else:
            # Not sure if XCode can be spefically handled by conan for building through, so assume everything not VS is make
            # Use genie with gmake gen, then make on specific projects based on requirements
            # gcc-multilib and g++-multilib required for 32bit cross-compilation, should see if we can check and install through conan
            
            # Generate projects through genie
            genieGen = f"{self.genieExtra} {self.gccOsToGenie[str(self.settings.os)]} gmake"
            self.run(f"{genie} {genieGen}", cwd=self.bimgPath)

            # Build project folder and path from given settings
            projFolder = f"gmake-{self.gmakeOsToProj[str(self.settings.os)]}"
            if self.osToUseArchConfigSuffix[str(self.settings.os)]:
                projFolder += self.gmakeArchToGenieSuffix[str(self.settings.arch)]
            projPath = os.path.sep.join([self.bimgPath, ".build", "projects", projFolder])

            # Build make args from settings
            conf = self.buildTypeToMakeConfig[str(self.settings.build_type)]
            if self.osToUseMakeConfigSuffix[str(self.settings.os)]:
                conf += self.archToMakeConfigSuffix[str(self.settings.arch)]
            autotools = Autotools(self)
            # Build with make
            for proj in self.projs:
                autotools.make(target=proj, args=["-R", f"-C {projPath}", conf])

    def package(self):
        # Get build bin folder
        for dir in os.listdir(os.path.join(self.bimgPath, ".build")):
            if not dir=="projects":
                buildBin = os.path.join(self.bimgPath, ".build", dir, "bin")
                break

        # Copy license
        copy(self, pattern="LICENSE", dst=os.path.join(self.package_folder, "licenses"), src=self.bimgPath)
        # Copy includes
        copy(self, pattern="*.h", dst=os.path.join(self.package_folder, "include"), src=os.path.join(self.bimgPath, "include"))
        copy(self, pattern="*.inl", dst=os.path.join(self.package_folder, "include"), src=os.path.join(self.bimgPath, "include"))
        # Copy libs
        if len(copy(self, pattern=self.libExt[0], dst=os.path.join(self.package_folder, "lib"), src=buildBin, keep_path=False))  < self.expectedNumLibs:
            raise Exception(self.invalidPackageExceptionText)
        # Debug info files are optional, so no checking
        if len(self.libExt) > 1:
            for ind in range(1, len(self.libExt)):
                copy(self, pattern=self.libExt[ind], dst=os.path.join(self.package_folder, "lib"), src=buildBin, keep_path=False)
        
        # Copy tools
        if self.options.tools:
            copy(self, pattern=f"texturec*", dst=os.path.join(self.package_folder, "bin"), src=buildBin, keep_path=False)
        
        # Rename for consistency across platforms and configs
        for bimgFile in Path(f"{self.package_folder}/lib").glob("*bimg*"):
            fExtra = ""
            if bimgFile.name.find("encode") >= 0:
                fExtra = "_encode"
            elif bimgFile.name.find("decode") >= 0:
                fExtra = "_decode"
            rename(self, os.path.join(self.package_folder, "lib", bimgFile.name),
                os.path.join(self.package_folder, "lib", f"{self.packageLibPrefix}bimg{fExtra}{bimgFile.suffix}"))
        for bimgFile in Path(os.path.join(self.package_folder, "bin")).glob("*texturec*"):
            rename(self, os.path.join(self.package_folder, "bin", bimgFile.name), 
                    os.path.join(self.package_folder, "bin", f"texturec{bimgFile.suffix}"))
        
        rm(self, pattern="*bx*", folder=os.path.join(self.package_folder, "lib")) 
        #for ext in self.libExt:
        #    rm(self, pattern=ext, folder=os.path.join(self.package_folder, "bin")) 
        #rm(self, pattern="*.exp", folder=os.path.join(self.package_folder, "bin")) 

    def package_info(self):
        self.cpp_info.includedirs = ["include"]
        self.cpp_info.libs = ["bimg_encode", "bimg_decode", "bimg"]

        self.cpp_info.set_property("cmake_file_name", "bimg")
        self.cpp_info.set_property("cmake_target_name", "bimg::bimg")
        self.cpp_info.set_property("pkg_config_name", "bimg")

        #  TODO: to remove in conan v2 once cmake_find_package_* generators removed
        self.cpp_info.filenames["cmake_find_package"] = "bimg"
        self.cpp_info.filenames["cmake_find_package_multi"] = "bimg"
        self.cpp_info.names["cmake_find_package"] = "bimg"
        self.cpp_info.names["cmake_find_package_multi"] = "bimg"
