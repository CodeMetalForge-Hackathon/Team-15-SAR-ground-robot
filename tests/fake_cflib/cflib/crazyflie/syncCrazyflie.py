class SyncCrazyflie:
    def __init__(self, uri, cf=None):
        self.uri, self.cf = uri, cf

    def open_link(self):
        self.cf.open_link(self.uri)

    def wait_for_params(self):
        pass

    def close_link(self):
        self.cf.close_link()
