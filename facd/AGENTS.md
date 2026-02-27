1. The web frontend is divided into "components". Each component has a file static/$COMPONENT.css and static/$COMPONENT.script.

1. The style of a tag should never be set directly in HTML/javascript. Instead, you should et the id/class of the tag in HTML/javascript and have a separate CSS file that defines the style for that class.
