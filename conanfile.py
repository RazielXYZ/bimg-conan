from conans import ConanFile, tools, MSBuild, AutoToolsBuildEnvironment
from conan.tools.microsoft import is_msvc
from conan.tools.build import check_min_cppstd
from conan.tools.scm import Version
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

    def package_id(self):
        if is_msvc(self):
            del self.info.settings.compiler.cppstd

    def validate(self):
        if self.settings.compiler.get_safe("cppstd"):
            check_min_cppstd(self, 14)
        if Version(self.version) < "1.3.30" and self.settings.os in ["Linux", "FreeBSD"] and self.settings.arch == "x86_64" and self.settings_build.arch == "x86":
            raise ConanInvalidConfiguration("This version of the package cannot be cross-built to Linux x86 due to old astc breaking that.")

    def configure(self):
        if self.settings.os == "Windows":
            self.libExt = ["*.lib", "*.pdb"]
            self.packageLibPrefix = ""
            self.binFolder = "windows"
        elif self.settings.os == "Linux":
            self.libExt = ["*.a"]
            self.packageLibPrefix = "lib"
            self.binFolder = "linux"
        self.toolsFolder = cwd=os.path.sep.join([".", "tools", "bin", self.binFolder])

    def set_version(self):
        self.output.info("Setting version from git.")
        tools.rmdir(self.bimgFolder)
        git = tools.Git(folder=self.bimgFolder)
        git.clone(f"{self.homepage}.git", "master")

        # Hackjob semver! Versioning by commit seems rather annoying for users, so let's version by commit count
        numCommits = int(git.run("rev-list --count master"))
        verMajor = 1 + (numCommits // 10000)
        verMinor = (numCommits // 100) % 100
        verRev = numCommits % 100
        self.output.highlight(f"Version {verMajor}.{verMinor}.{verRev}")
        self.version = f"{verMajor}.{verMinor}.{verRev}"

    def source(self):
        # bimg requires bx source to build;
        self.output.info("Getting source")
        gitBx = tools.Git(folder=self.bxFolder)
        gitBx.clone("https://github.com/bkaradzic/bx.git", "master")
        gitBimg = tools.Git(folder=self.bimgFolder)
        gitBimg.clone(f"{self.homepage}.git", "master")

    def build(self):
        # Map conan compilers to genie input
        genie = os.path.sep.join(["..", self.bxFolder, self.toolsFolder, "genie"])
        if is_msvc(self):
            # Use genie directly, then msbuild on specific projects based on requirements
            genieGen = f"vs{self.vsVerToGenie[str(self.settings.compiler.version)]}"
            self.output.highlight(genieGen)
            self.run(f"{genie} {genieGen}", cwd=self.bimgFolder)
            msbuild = MSBuild(self)
            msbuild.build(f"{self.bimgFolder}\\.build\\projects\\{genieGen}\\bimg.vcxproj")
            msbuild.build(f"{self.bimgFolder}\\.build\\projects\\{genieGen}\\bimg_encode.vcxproj")
            msbuild.build(f"{self.bimgFolder}\\.build\\projects\\{genieGen}\\bimg_decode.vcxproj")
        else:
            # Not sure if XCode can be spefically handled by conan for building through, so assume everything not VS is make
            # Use genie with gmake gen, then make on specific projects based on requirements
            # gcc-multilib and g++-multilib required for 32bit cross-compilation, should see if we can check and install through conan
            
            # Generate projects through genie
            genieGen = f"{self.gccOsToGenie[str(self.settings.os)]} gmake"
            self.run(f"{genie} {genieGen}", cwd=self.bimgFolder)

            # Build project folder and path from given settings
            projFolder = f"gmake-{self.gmakeOsToProj[str(self.settings.os)]}"
            if self.osToUseArchConfigSuffix[str(self.settings.os)]:
                projFolder += self.gmakeArchToGenieSuffix[str(self.settings.arch)]
            projPath = os.path.sep.join([".", self.bimgFolder, ".build", "projects", projFolder])

            autotools = AutoToolsBuildEnvironment(self)
            with tools.environment_append(autotools.vars):
                # Build make args from settings
                conf = self.buildTypeToMakeConfig[str(self.settings.build_type)]
                if self.osToUseMakeConfigSuffix[str(self.settings.os)]:
                    conf += self.archToMakeConfigSuffix[str(self.settings.arch)]

                # Compile with make
                self.run(f"make {conf}", cwd=projPath)

    def package(self):
        # Copy includes
        self.copy("*.h", dst="include", src=f"{self.bimgFolder}/include/")
        self.copy("*.inl", dst="include", src=f"{self.bimgFolder}/include/")
        # Copy libs and debug info
        if len(self.copy(self.libExt[0], dst="lib", src=f"{self.bimgFolder}/.build/", keep_path=False))  < self.expectedNumLibs:
            raise Exception(self.invalidPackageExceptionText)
        # Debug info files are optional, so no checking
        if len(self.libExt) > 1:
            for ind in range(1, len(self.libExt)):
                self.copy(self.libExt[ind], dst="lib", src=f"{self.bimgFolder}/.build/", keep_path=False)
        # Rename to strip Debug/Release suffix from libs
        for bimgFile in Path(f"{self.package_folder}/lib").glob("*bimg*"):
            fExtra = ""
            if bimgFile.name.find("encode") >= 0:
                fExtra = "_encode"
            elif bimgFile.name.find("decode") >= 0:
                fExtra = "_decode"
            tools.rename(f"{self.package_folder}/lib/{bimgFile.name}", f"{self.package_folder}/lib/{self.packageLibPrefix}bimg{fExtra}{bimgFile.suffix}")
        tools.remove_files_by_mask(f"{self.package_folder}/lib", "*bx*")
            

    def package_info(self):
        self.cpp_info.includedirs = ["include"]
        self.cpp_info.libs = ["bimg_decode", "bimg_encode", "bimg"]

        self.cpp_info.set_property("cmake_file_name", "bimg")
        self.cpp_info.set_property("cmake_target_name", "bimg::bimg")
        self.cpp_info.set_property("pkg_config_name", "bimg")

        #  TODO: to remove in conan v2 once cmake_find_package_* generators removed
        self.cpp_info.filenames["cmake_find_package"] = "bimg"
        self.cpp_info.filenames["cmake_find_package_multi"] = "bimg"
        self.cpp_info.names["cmake_find_package"] = "bimg"
        self.cpp_info.names["cmake_find_package_multi"] = "bimg"
