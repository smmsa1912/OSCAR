import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:oscar_ag/main.dart';

void main() {
  test('desktop app root widget can be created', () {
    expect(const OscarDesktopApp(), isA<Widget>());
  });
}
