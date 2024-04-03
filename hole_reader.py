#
# Copyright (C) 2024 by Florian Wesch <fw@dividuum.de>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
import os, sys, errno

class DataSection:
    all_zero = False

    def __init__(self, reader, size):
        self._reader = reader
        self._remaining = size

    def read(self, max_size=2**18):
        if self._remaining is None:
            return self._reader.read(max_size)
        read_size = min(max_size, self._remaining)
        if read_size == 0:
            return b''
        buf = self._reader.read(read_size)
        self._remaining -= len(buf)
        return buf

    def skip(self):
        raise NotImplementedError

class HoleSection:
    all_zero = True

    def __init__(self, reader, size):
        self._reader = reader
        self._remaining = size

    def read(self, max_size):
        read_size = min(max_size, self._remaining)
        if read_size == 0:
            return b''
        buf = bytearray(read_size)
        self._reader.advance(read_size)
        self._remaining -= read_size
        return buf

    def skip(self):
        skipped = self._reader.advance(self._remaining)
        self._remaining = 0
        return skipped

class HoleReader:
    def __init__(self, fname):
        self._fd = os.open(fname, os.O_RDONLY)
        self._offset = 0
        self._eof = False
        self._seekable = True
        try:
            os.lseek(self._fd, 0, os.SEEK_SET)
        except OSError as err:
            if err.errno == errno.ESPIPE:
                self._seekable = False
            else:
                raise
        if self._seekable:
            self._size = os.fstat(self._fd).st_size
        else:
            self._size = None
        self.detect_initial_mode()

    @property
    def seekable(self):
        return self._seekable

    def read(self, size):
        if self._eof:
            return b''
        buf = os.read(self._fd, size)
        self.advance(len(buf))
        if not buf:
            self._eof = True
        return buf

    def advance(self, size):
        self._offset += size
        if self._size is not None and self._offset >= self._size:
            self._eof = True
        return size

    def detect_initial_mode(self):
        if not self._seekable:
            self._in_data = True
            return
        self._in_data = False
        try:
            self._in_data = os.lseek(self._fd, 0, os.SEEK_DATA) == 0
        except:
            pass # one single large hole spanning whole file

    def detect_section_size(self):
        if not self._seekable:
            return None
        try:
            next_cut = os.lseek(
                self._fd,
                self._offset,
                (os.SEEK_DATA, os.SEEK_HOLE)[self._in_data],
            )
        except OSError as err:
            if err.errno == errno.ENXIO:
                next_cut = self._size
            else:
                raise
        os.lseek(self._fd, self._offset, os.SEEK_SET)
        return next_cut - self._offset

    def __iter__(self):
        while not self._eof:
            section_size = self.detect_section_size()
            if self._in_data:
                yield DataSection(self, section_size)
            else:
                yield HoleSection(self, section_size)
            self._in_data = not self._in_data


if __name__ == "__main__":
    r = HoleReader(sys.argv[1])
    print(f'seekable: {r.seekable}')

    total_read = 0
    for section in r:
        print('- - - - - - - - -')
        print(f'all zero? {section.all_zero}')
        if section.all_zero:
            read = section.skip()
        else:
            read = 0
            while 1:
                buf = section.read(1024)
                read += len(buf)
                if not buf:
                    break
        print(f'read in section: {read}')
        total_read += read
    print(f'total data: {total_read}')
