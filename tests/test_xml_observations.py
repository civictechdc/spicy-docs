"""Current-element capture matches the ancestry snapshot without copying it.

Namespace-qualified attributes survive caller mutation, and source_xpath positions each element 1-based among siblings.
"""

from spicy_docs.reading.xml_observations import XmlObservationScan


def test_current_element_matches_ancestry_snapshot_with_namespaces_and_siblings():
    positions = []

    class Observe(XmlObservationScan):
        def observe_start(self, tag, attributes):
            current = self.current_element()
            assert current == self.snapshot()[-1]
            positions.append(current.source_xpath)
            current.attributes.clear()
            assert self.current_element().attributes == attributes

    scan = Observe(error_type=ValueError, label="fixture")
    scan.read(
        b'<x:root xmlns:x="urn:x" x:a="raw"><skip/><x:item n="1"><leaf/></x:item><x:item/></x:root>', max_bytes=1024
    )
    assert positions == ["/*[1]", "/*[1]/*[1]", "/*[1]/*[2]", "/*[1]/*[2]/*[1]", "/*[1]/*[3]"]
