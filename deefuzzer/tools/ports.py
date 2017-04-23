import socket


def port_is_available(port, address='localhost'):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    available = None
    try:
        s.bind((address, port))
        available = True
    except socket.error as e:
        if e.errno == 98:
            # Port is already in use
            available = False
    finally:
        s.close()

    return available


if __name__ == '__main__':
    import sys
    from optparse import OptionParser
    parser = OptionParser()

    parser.add_option("-a", "--address", dest="address",
                      default='localhost',
                      help="ADDRESS for server", metavar="ADDRESS")

    parser.add_option("-p", "--port", dest="port", type="int",
                      default=80, help="PORT for server", metavar="PORT")

    (options, args) = parser.parse_args()
    print 'options: %s, args: %s' % (options, args)
    check = port_is_available(options.port, address=options.address)
    print 'check_server returned %s' % check

    sys.exit(not check)
