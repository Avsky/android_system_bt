#
# Copyright 2015 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Script for sending testing parameters and commands to a Bluetooth device.

This script provides a simple shell interface for sending data at run-time to a
Bluetooth device. It is intended to be used in tandem with the test vendor
library project.

Usage:
  Option A: Script
    1. Run build_and_run.sh in scripts/ with the --test-channel flag set and the
    port to use for the test channel.
  Option B: Manual
    1. Choose a port to use for the test channel. Use 'adb forward tcp:<port>
    tcp:<port>' to forward the port to the device.
    2. In a separate shell, build and push the test vendor library to the device
    using the script mentioned in option A (i.e. without the --test-channel flag
    set).
    3. Once logcat has started, turn Bluetooth on from the device.
    4. Run this program, in the shell from step 1, with address 'localhost' and
    the port, also from step 1, as arguments.
"""

#!/usr/bin/env python

import cmd
import random
import socket
import string
import struct
import sys

DEVICE_NAME_LENGTH = 6
DEVICE_ADDRESS_LENGTH = 6

# Used to generate fake device names and addresses during discovery.
def generate_random_name():
  return ''.join(random.SystemRandom().choice(string.ascii_uppercase + \
    string.digits) for _ in range(DEVICE_NAME_LENGTH))

def generate_random_address():
  return ''.join(random.SystemRandom().choice(string.digits) for _ in \
    range(DEVICE_ADDRESS_LENGTH))

class Connection(object):
  """Simple wrapper class for a socket object.

  Attributes:
    socket: The underlying socket created for the specified address and port.
  """

  def __init__(self, address, port):
    self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self._socket.connect((address, port))

  def close(self):
    self._socket.close()

  def send(self, data):
    self._socket.sendall(data)

class TestChannel(object):
  """Checks outgoing commands and sends them once verified.

  Attributes:
    connection: The connection to the test vendor library that commands are sent
    on.
  """

  def __init__(self, address, port):
    self._connection = Connection(address, port)
    self._discovered_devices = DeviceManager()

  def discover_new_device(self, name=None, address=None):
    device = Device(name, address)
    self._discovered_devices.add_device(device)
    return device

  def close(self):
    self._connection.close()

  def send_command(self, name, args):
    name_size = len(name)
    args_size = len(args)
    self.lint_command(name, args, name_size, args_size)
    encoded_name = chr(name_size) + name
    encoded_args = chr(args_size) + ''.join(chr(len(arg)) + arg for arg in args)
    command = encoded_name + encoded_args
    self._connection.send(command)

  def lint_command(self, name, args, name_size, args_size):
    assert name_size == len(name) and args_size == len(args)
    try:
      name.encode('utf-8')
      for arg in args:
        arg.encode('utf-8')
    except UnicodeError:
      print 'Unrecognized characters.'
      raise
    if name_size > 255 or args_size > 255:
      raise ValueError  # Size must be encodable in one octet.
    for arg in args:
      if len(arg) > 255:
        raise ValueError  # Size must be encodable in one octet.

class DeviceManager(object):
  """Maintains the active fake devices that have been "discovered".

  Attributes:
    device_list: Maps device addresses (keys) to devices (values).
  """

  def __init__(self):
    self.device_list = {}

  def add_device(self, device):
    self.device_list[device.get_address()] = device

class Device(object):
  """A fake device to be returned in inquiry and scan results. Note that if an
  explicit name or address is not provided, a random string of characters
  is used.

  Attributes:
    name: The device name for use in extended results.
    address: The BD address of the device.
  """

  def __init__(self, name=None, address=None):
    # TODO(dennischeng): Generate device properties more robustly.
    self.name = generate_random_name() if name is None else name
    self.address = generate_random_address() if address is None else address

  def get_name(self):
    return self.name

  def get_address(self):
    return self.address

class TestChannelShell(cmd.Cmd):
  """Shell for sending test channel data to controller.

  Manages the test channel to the controller and defines a set of commands the
  user can send to the controller as well. These commands are processed parallel
  to commands sent from the device stack and used to provide additional
  debugging/testing capabilities.

  Attributes:
    test_channel: The communication channel to send data to the controller.
  """

  def __init__(self, test_channel):
    print 'Type \'help\' for more information.'
    cmd.Cmd.__init__(self)
    self._connection = Connection(address, port)

  def do_hci_reset(self, arg):
    """Sends an HCIReset command to the controller."""
    self._connection.send(struct.pack('4b', 1, 3, 0xC, 0))

  def do_quit(self, arg):
    """Exits the test channel."""
    self._connection.close()
    self._test_channel = test_channel

  def do_timeout_all(self, args):
    """
    Arguments: None.
    Causes all HCI commands to timeout.
    """
    self._test_channel.send_command('TIMEOUT_ALL', [])

  def do_discover(self, args):
    """
    Arguments: name_1 name_2 ...
    Sends an inquiry result for device(s) |name|. If no names are provided, a
    random name is used instead.
    """
    if len(args) == 0:
      args = generate_random_name()
    device_list = [self.test_channel.discover_new_device(arg) for arg in \
                   args.split()]
    device_names_and_addresses = []
    for device in device_list:
      device_names_and_addresses.append(device.get_name())
      device_names_and_addresses.append(device.get_address())
    self._test_channel.send_command('DISCOVER', device_names_and_addresses)

  def do_discover_interval(self, args):
    """
    Arguments: interval_in_ms
    Sends an inquiry result for a device with a random name on the interval
    specified by |interval_in_ms|.
    """
    args.append(generate_random_name())
    args.append(generate_random_address())
    self._test_channel.send_command('DISCOVER_INTERVAL', args.split())

  def do_clear(self, args):
    """
    Arguments: None.
    Resets the controller to its original, unmodified state.
    """
    self._test_channel.send_command('CLEAR', [])

  def do_quit(self, args):
    """
    Arguments: None.
    Exits the test channel.
    """
    self._test_channel.send_command('CLOSE_TEST_CHANNEL', [])
    self._test_channel.close()
    print 'Goodbye.'
    return True

def main(argv):
  if len(argv) != 3:
    print 'Usage: python test_channel.py [address] [port]'
    return
  try:
    address = str(argv[1])
    port = int(argv[2])
  except ValueError:
    print 'Error parsing address or port.'
  else:
    try:
      test_channel = TestChannel(address, port)
    except socket.error, e:
      print 'Error connecting to socket: %s' % e
    except:
      print 'Error creating test channel (check arguments).'
    else:
      test_channel.prompt = '$ '
      test_channel.cmdloop()

if __name__ == '__main__':
  main(sys.argv)