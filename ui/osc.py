from pythonosc.udp_client import SimpleUDPClient


class OSC:
  def __init__(self, ip='127.0.0.1', port=6667):
    self.ip = ip
    self.port = port
    self.client = SimpleUDPClient(self.ip, self.port)

  def send(self, address, message):
    assert len(address) > 1 and address[0] == '/'
    assert message is not None
    self.client.send_message(address, message)

  def set_destination(self, ip, port=None):
    if port is not None:
      self.port = int(port)

    self.ip = ip
    self.client = SimpleUDPClient(self.ip, self.port)

    print(
      f"OSC destination changed to {self.ip}:{self.port}"
    )

  def get_destination(self):
    return self.ip, self.port