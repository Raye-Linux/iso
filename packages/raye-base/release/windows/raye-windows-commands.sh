# Windows command names typed in a terminal (notepad, regedit, control...)
# open the Raye app that does the job. Last on the PATH, so a real program
# of the same name always wins.
case ":$PATH:" in
    *:/usr/lib/raye/windows/commands:*) ;;
    *) PATH="${PATH:+$PATH:}/usr/lib/raye/windows/commands" ;;
esac
